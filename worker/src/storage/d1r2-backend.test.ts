import { describe, expect, it } from "vitest";
import { InMemoryD1Database } from "../test/d1-mock";
import { InMemoryR2Bucket } from "../test/r2-mock";
import { isEncrypted } from "./crypto";
import { D1R2Backend } from "./d1r2-backend";
import { USER_BOOKMARK, USER_REFRESH_TOKENS } from "./keys";
import { userR2Path } from "./r2-keys";

const TEST_KEY = "a".repeat(64);

function makeBackend(encryptAtRest = true) {
  const db = new InMemoryD1Database();
  const data = new InMemoryR2Bucket();
  const store = new D1R2Backend(
    { DB: db, DATA: data, STORAGE_ENCRYPTION_KEY: TEST_KEY },
    { encryptAtRest },
  );
  return { store, data };
}

describe("D1R2Backend", () => {
  it("users registry roundtrip via D1", async () => {
    const { store } = makeBackend();
    const users = [{ username: "alice", password_hash: "x", created_at: 1, theme: "dark" }];
    await store.saveUsers(users);
    expect(await store.loadUsers()).toEqual(users);
  });

  it("encrypts sensitive user blobs in R2", async () => {
    const { store, data: r2 } = makeBackend();
    await store.putBlob("alice", USER_REFRESH_TOKENS, "[]");
    const onR2 = r2.getStored(userR2Path("alice", USER_REFRESH_TOKENS));
    expect(onR2).toBeDefined();
    expect(isEncrypted(onR2!)).toBe(true);
    expect(await store.getBlob("alice", USER_REFRESH_TOKENS)).toBe("[]");
  });

  it("reads legacy plaintext blobs from R2", async () => {
    const { store, data: r2 } = makeBackend();
    await r2.put(userR2Path("bob", USER_REFRESH_TOKENS), "[]");
    expect(await store.getBlob("bob", USER_REFRESH_TOKENS)).toBe("[]");
  });

  it("lists user blobs via D1 index", async () => {
    const { store } = makeBackend();
    await store.putBlob("alice", USER_REFRESH_TOKENS, "[]");
    await store.putBlob("alice", USER_BOOKMARK, "{}");
    const keys = await store.listBlobs("alice");
    expect(keys).toEqual([USER_BOOKMARK, USER_REFRESH_TOKENS]);
  });

  it("delete removes R2 object and index row", async () => {
    const { store, data: r2 } = makeBackend();
    await store.putBlob("alice", USER_BOOKMARK, "{}");
    expect(await store.blobExists("alice", USER_BOOKMARK)).toBe(true);
    await store.deleteBlob("alice", USER_BOOKMARK);
    expect(await store.blobExists("alice", USER_BOOKMARK)).toBe(false);
    expect(r2.getStored(userR2Path("alice", USER_BOOKMARK))).toBeUndefined();
  });
});