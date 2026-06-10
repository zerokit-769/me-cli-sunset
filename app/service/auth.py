import os
import json
import time
from app.client.ciam import get_new_token
from app.client.engsel import get_profile
from app.util import ensure_api_key

class Auth:
    _instance_ = None
    _initialized_ = False

    api_key = ""

    refresh_tokens = []
    # Format of refresh_tokens:
    # [
        # {
            # "number": int,
            # "subscriber_id": str,
            # "subscription_type": str,
            # "refresh_token": str
        # }
    # ]

    active_user = None
    # {
    #     "number": int,
    #     "subscriber_id": str,
    #     "subscription_type": str,
    #     "tokens": {
    #         "refresh_token": str,
    #         "access_token": str,
    #         "id_token": str
	#     }
    # }
    
    last_refresh_time = None
    
    def __new__(cls, *args, **kwargs):
        if not cls._instance_:
            cls._instance_ = super().__new__(cls)
        return cls._instance_
    
    def __init__(self):
        if not self._initialized_:
            self.api_key = ensure_api_key()
            self.reload_for_current_dir()
            self._initialized_ = True

    def reload_for_current_dir(self):
        """Reset state and re-read tokens/active-user from current working dir.
        Called by webui middleware after switching to a per-user dir."""
        self.refresh_tokens = []
        self.active_user = None
        if os.path.exists("refresh-tokens.json"):
            try:
                self.load_tokens()
            except Exception as e:
                print(f"[auth.reload] load_tokens err: {e}")
        else:
            with open("refresh-tokens.json", "w", encoding="utf-8") as f:
                json.dump([], f, indent=4)
        try:
            self.load_active_number()
        except Exception as e:
            print(f"[auth.reload] load_active_number err: {e}")
        self.last_refresh_time = int(time.time())
            
    def load_tokens(self):
        with open("refresh-tokens.json", "r", encoding="utf-8") as f:
            refresh_tokens = json.load(f)
            
            if len(refresh_tokens) !=  0:
                self.refresh_tokens = []

            # Validate and load tokens
            for rt in refresh_tokens:
                if "number" in rt and "refresh_token" in rt:
                    self.refresh_tokens.append(rt)
                else:
                    print(f"Invalid token entry: {rt}")

    def add_refresh_token(self, number: int, refresh_token: str):
        # Check if number already exist, if yes, replace it, if not append
        existing = next((rt for rt in self.refresh_tokens if rt["number"] == number), None)
        if existing:
            existing["refresh_token"] = refresh_token
        else:
            tokens = get_new_token(self.api_key, refresh_token, "")
            profile_data = get_profile(self.api_key, tokens["access_token"], tokens["id_token"]) or {}
            profile = profile_data.get("profile") or {}
            sub_id = profile.get("subscriber_id") or ""
            sub_type = profile.get("subscription_type") or "PREPAID"

            self.refresh_tokens.append({
                "number": int(number),
                "subscriber_id": sub_id,
                "subscription_type": sub_type,
                "refresh_token": refresh_token
            })
        
        # Save to file
        self.write_tokens_to_file()

        # Set active user to newly added
        self.set_active_user(number)
            
    def remove_refresh_token(self, number: int):
        self.refresh_tokens = [rt for rt in self.refresh_tokens if rt["number"] != number]
        
        # Save to file
        with open("refresh-tokens.json", "w", encoding="utf-8") as f:
            json.dump(self.refresh_tokens, f, indent=4)
        
        # If the removed user was the active user, select a new active user if available
        if self.active_user and self.active_user["number"] == number:
            self.active_user = None
            # Select the first user as active user by default
            if len(self.refresh_tokens) != 0:
                first_rt = self.refresh_tokens[0]
                try:
                    tokens = get_new_token(self.api_key, first_rt["refresh_token"], first_rt.get("subscriber_id", ""))
                    if tokens:
                        self.set_active_user(first_rt["number"])
                except Exception as e:
                    print(f"Failed to activate next after remove {number}: {e}")
            else:
                print("No users left.")
                if os.path.exists("active.number"):
                    try:
                        os.remove("active.number")
                    except Exception:
                        pass

    def set_active_user(self, number: int):
        # Get refresh token for the number from refresh_tokens
        rt_entry = next((rt for rt in self.refresh_tokens if rt["number"] == number), None)
        if not rt_entry:
            print(f"No refresh token found for number: {number}")
            return False

        try:
            tokens = get_new_token(self.api_key, rt_entry["refresh_token"], rt_entry.get("subscriber_id", ""))
            if not tokens:
                print(f"Failed to get tokens for number: {number}. The refresh token might be invalid or expired.")
                self.remove_refresh_token(number)
                return False

            profile_data = get_profile(self.api_key, tokens["access_token"], tokens["id_token"]) or {}
            profile = profile_data.get("profile") or {}
            subscriber_id = profile.get("subscriber_id") or rt_entry.get("subscriber_id", "")
            subscription_type = profile.get("subscription_type") or rt_entry.get("subscription_type", "PREPAID")

            self.active_user = {
                "number": int(number),
                "subscriber_id": subscriber_id,
                "subscription_type": subscription_type,
                "tokens": tokens
            }
            
            # Update refresh token entry with subscriber_id and subscription_type
            rt_entry["subscriber_id"] = subscriber_id
            rt_entry["subscription_type"] = subscription_type
            
            # Update refresh token. The real client app do this, not sure why cz refresh token should still be valid
            rt_entry["refresh_token"] = tokens["refresh_token"]
            self.write_tokens_to_file()
            
            self.last_refresh_time = int(time.time())
            
            # Save active number to file
            self.write_active_number()
            return True
        except Exception as e:
            err = str(e)
            print(f"Error activating number {number}: {err}")
            # Auto-clean invalid/expired tokens so user isn't stuck
            if any(kw in err.lower() for kw in ["invalid or expired", "session not active", "subscriber id is missing", "refresh token"]):
                print(f"Auto-removing invalid token for {number}")
                self.remove_refresh_token(number)
            if self.active_user and self.active_user.get("number") == number:
                self.active_user = None
            return False

    def renew_active_user_token(self):
        if self.active_user:
            try:
                tokens = get_new_token(self.api_key, self.active_user["tokens"]["refresh_token"], self.active_user.get("subscriber_id", ""))
                if tokens:
                    self.active_user["tokens"] = tokens
                    self.last_refresh_time = int(time.time())
                    self.add_refresh_token(self.active_user["number"], self.active_user["tokens"]["refresh_token"])
                    
                    print("Active user token renewed successfully.")
                    return True
                else:
                    print("Failed to renew active user token.")
                    num = self.active_user.get("number")
                    if num:
                        self.remove_refresh_token(num)
                    self.active_user = None
            except Exception as e:
                print(f"Renew error: {e}")
                num = self.active_user.get("number") if self.active_user else None
                if num and any(kw in str(e).lower() for kw in ["invalid", "expired", "session not active"]):
                    self.remove_refresh_token(num)
                self.active_user = None
        else:
            print("No active user set or missing refresh token.")
        return False
    
    def get_active_user(self):
        if not self.active_user:
            # Try to activate the first valid one, cleaning bad tokens along the way
            for rt in list(self.refresh_tokens):  # copy because remove may mutate
                try:
                    tokens = get_new_token(self.api_key, rt["refresh_token"], rt.get("subscriber_id", ""))
                    if tokens:
                        if self.set_active_user(rt["number"]):
                            break
                except Exception as e:
                    print(f"Bootstrap get_new failed for {rt.get('number')}: {e}")
                    self.remove_refresh_token(rt["number"])
            if not self.active_user:
                return None
        
        if self.last_refresh_time is None or (int(time.time()) - self.last_refresh_time) > 300:
            try:
                self.renew_active_user_token()
            except Exception as e:
                print(f"Renew failed: {e}")
                # if current active is bad, clean it
                if self.active_user:
                    num = self.active_user.get("number")
                    try:
                        # force a get_new to see
                        get_new_token(self.api_key, self.active_user["tokens"]["refresh_token"], self.active_user.get("subscriber_id", ""))
                    except Exception:
                        if num:
                            self.remove_refresh_token(num)
                        self.active_user = None
            self.last_refresh_time = time.time()
        
        return self.active_user
    
    def get_active_tokens(self) -> dict | None:
        active_user = self.get_active_user()
        return active_user["tokens"] if active_user else None
    
    def write_tokens_to_file(self):
        with open("refresh-tokens.json", "w", encoding="utf-8") as f:
            json.dump(self.refresh_tokens, f, indent=4)
    
    def write_active_number(self):
        if self.active_user:
            with open("active.number", "w", encoding="utf-8") as f:
                f.write(str(self.active_user["number"]))
        else:
            if os.path.exists("active.number"):
                os.remove("active.number")
    
    def load_active_number(self):
        if os.path.exists("active.number"):
            with open("active.number", "r", encoding="utf-8") as f:
                number_str = f.read().strip()
                if number_str.isdigit():
                    number = int(number_str)
                    success = self.set_active_user(number)
                    if not success:
                        # Bad active saved → clear it so we don't keep trying the dead one
                        try:
                            if os.path.exists("active.number"):
                                os.remove("active.number")
                        except Exception:
                            pass
                        self.active_user = None

AuthInstance = Auth()
