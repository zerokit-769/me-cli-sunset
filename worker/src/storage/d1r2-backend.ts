import { utf8Decode, utf8Encode } from "../crypto/encoding";
import { decryptBytes, encryptBytes, resolveEncryptionKey } from "./crypto";
import { GLOBAL_SESSION_SECRET, GLOBAL_USERS_REGISTRY, isEncryptedKey, normalizeBlobKey } from "./keys";
import { resolveBlobLocation } from "./r2-keys";
import type { StorageBackend, StorageBindings, WebUIUser } from "./types";

export interface D1R2BackendOptions {
  encryptAtRest?: boolean;
}

function nowSec(): number {
  return Math.floor(Date.now() / 1000);
}

function randomSecret(bytes = 32): Uint8Array {
  return crypto.getRandomValues(new Uint8Array(bytes));
}

function decodeSessionSecret(raw: string): Uint8Array {
  const trimmed = raw.trim();
  if (!trimmed) return new Uint8Array();
  try {
    const binary = atob(trimmed);
    const out = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) out[i] = binary.charCodeAt(i);
    return out;
  } catch {
    return utf8Encode(trimmed);
  }
}

export class D1R2Backend implements StorageBackend {
  private readonly encryptAtRest: boolean;

  constructor(
    private readonly env: StorageBindings,
    options: D1R2BackendOptions = {},
  ) {
    this.encryptAtRest = options.encryptAtRest ?? true;
  }

  private async encryptionKey(): Promise<Uint8Array> {
    return resolveEncryptionKey(this.env.STORAGE_ENCRYPTION_KEY, await this.getSessionSecret());
  }

  private async maybeDecrypt(objectKey: string, raw: Uint8Array): Promise<Uint8Array> {
    if (!this.encryptAtRest || !isEncryptedKey(objectKey)) return raw;
    try {
      return await decryptBytes(raw, await this.encryptionKey());
    } catch {
      return raw;
    }
  }

  private async maybeEncrypt(objectKey: string, raw: Uint8Array): Promise<Uint8Array> {
    if (!this.encryptAtRest || !isEncryptedKey(objectKey)) return raw;
    return encryptBytes(raw, await this.encryptionKey());
  }

  async loadUsers(): Promise<WebUIUser[]> {
    const result = await this.env.DB.prepare(
      `SELECT username, password_hash, created_at, theme, telegram_chat_id
       FROM webui_users ORDER BY created_at ASC`,
    ).all<WebUIUser>();
    return (result.results ?? []).map((row) => {
      const user: WebUIUser = {
        username: row.username,
        password_hash: row.password_hash,
        created_at: row.created_at,
      };
      if (row.theme) user.theme = row.theme;
      if (row.telegram_chat_id != null) user.telegram_chat_id = row.telegram_chat_id;
      return user;
    });
  }

  async saveUsers(users: WebUIUser[]): Promise<void> {
    const ts = nowSec();
    const statements = [
      this.env.DB.prepare("DELETE FROM webui_users"),
      ...users.map((user) =>
        this.env.DB.prepare(
          `INSERT INTO webui_users (
             username, password_hash, created_at, theme, telegram_chat_id, updated_at
           ) VALUES (?, ?, ?, ?, ?, ?)`,
        ).bind(
          user.username.toLowerCase().trim(),
          user.password_hash,
          user.created_at || ts,
          user.theme ?? "dark",
          user.telegram_chat_id ?? null,
          ts,
        ),
      ),
    ];
    await this.env.DB.batch(statements);
  }

  async getSessionSecret(): Promise<Uint8Array> {
    if (this.env.SESSION_SECRET?.trim()) {
      const decoded = decodeSessionSecret(this.env.SESSION_SECRET);
      if (decoded.length) return decoded;
    }

    const row = await this.env.DB.prepare("SELECT value FROM storage_meta WHERE key = ?")
      .bind(GLOBAL_SESSION_SECRET)
      .first<{ value: ArrayBuffer }>();
    if (row?.value) return new Uint8Array(row.value);

    const secret = randomSecret(32);
    const ts = nowSec();
    await this.env.DB.prepare(
      `INSERT INTO storage_meta (key, value, updated_at) VALUES (?, ?, ?)`,
    )
      .bind(GLOBAL_SESSION_SECRET, secret, ts)
      .run();
    return secret;
  }

  async ensureUserDir(_username: string): Promise<void> {
    // R2 has no directories — index row created on first putBlob.
  }

  async getBlob(
    username: string | null,
    key: string,
    options: { binary?: boolean } = {},
  ): Promise<string | Uint8Array | null> {
    const loc = resolveBlobLocation(username, key);
    if (!loc) return null;

    const obj = await this.env.DATA.get(loc.r2Path);
    if (!obj) return null;

    const raw = new Uint8Array(await obj.arrayBuffer());
    const plain = await this.maybeDecrypt(loc.objectKey, raw);
    if (options.binary) return plain;
    return utf8Decode(plain);
  }

  async putBlob(
    username: string | null,
    key: string,
    data: string | Uint8Array,
    options: { binary?: boolean } = {},
  ): Promise<void> {
    const loc = resolveBlobLocation(username, key);
    if (!loc) return;

    const payload = typeof data === "string" ? utf8Encode(data) : data;
    const stored = await this.maybeEncrypt(loc.objectKey, payload);
    const ts = nowSec();

    await this.env.DATA.put(loc.r2Path, stored);
    await this.env.DB.prepare(
      `INSERT INTO r2_objects (scope, username, object_key, r2_path, size_bytes, updated_at)
       VALUES (?, ?, ?, ?, ?, ?)
       ON CONFLICT(scope, username, object_key) DO UPDATE SET
         r2_path = excluded.r2_path,
         size_bytes = excluded.size_bytes,
         updated_at = excluded.updated_at`,
    )
      .bind(loc.scope, loc.username, loc.objectKey, loc.r2Path, stored.byteLength, ts)
      .run();
  }

  async deleteBlob(username: string | null, key: string): Promise<void> {
    const loc = resolveBlobLocation(username, key);
    if (!loc) return;

    await this.env.DATA.delete(loc.r2Path);
    await this.env.DB.prepare(
      `DELETE FROM r2_objects WHERE scope = ? AND username = ? AND object_key = ?`,
    )
      .bind(loc.scope, loc.username, loc.objectKey)
      .run();
  }

  async blobExists(username: string | null, key: string): Promise<boolean> {
    const loc = resolveBlobLocation(username, key);
    if (!loc) return false;

    const row = await this.env.DB.prepare(
      `SELECT 1 AS ok FROM r2_objects WHERE scope = ? AND username = ? AND object_key = ?`,
    )
      .bind(loc.scope, loc.username, loc.objectKey)
      .first<{ ok: number }>();
    if (row) return true;

    const head = await this.env.DATA.head(loc.r2Path);
    return head !== null;
  }

  async listBlobs(username: string | null, prefix = ""): Promise<string[]> {
    const normalizedPrefix = normalizeBlobKey(prefix);

    if (normalizedPrefix.startsWith("shared/") || (!username && normalizedPrefix === "")) {
      const scope = normalizedPrefix.startsWith("shared/") ? "shared" : null;
      if (scope === "shared") {
        const like = `${normalizedPrefix}%`;
        const result = await this.env.DB.prepare(
          `SELECT object_key FROM r2_objects
           WHERE scope = 'shared' AND object_key LIKE ?
           ORDER BY object_key`,
        )
          .bind(like)
          .all<{ object_key: string }>();
        return (result.results ?? []).map((r) => r.object_key);
      }
    }

    const scope = username ? "user" : "cli";
    const uname = username ?? "";
    const like = normalizedPrefix ? `${normalizedPrefix}%` : "%";

    const result = await this.env.DB.prepare(
      `SELECT object_key FROM r2_objects
       WHERE scope = ? AND username = ? AND object_key LIKE ?
       ORDER BY object_key`,
    )
      .bind(scope, uname, like)
      .all<{ object_key: string }>();

    return (result.results ?? []).map((r) => r.object_key);
  }
}

export function createStorage(env: StorageBindings, options?: D1R2BackendOptions): StorageBackend {
  if (!env.DB || !env.DATA) {
    throw new Error("D1R2Backend requires DB and DATA bindings");
  }
  return new D1R2Backend(env, options);
}