import sys
from pathlib import Path


def replace_checked(text: str, needle: str, replacement: str) -> str:
    """Stop the build if an upstream change invalidates a required patch."""
    if replacement in text:
        return text
    if text.count(needle) != 1:
        raise RuntimeError(f"Native patch target changed or is ambiguous: {needle[:100]!r}")
    return text.replace(needle, replacement, 1)


root = Path(sys.argv[1])

# Python 3.12 allows backslashes inside f-string expressions; fnOS uses 3.11.
smb = root / "app/modules/filemanager/storages/smb.py"
text = smb.read_text(encoding="utf-8")
needle = '''            return f"{self._server_path}\\\\{path_str.replace('/', '\\\\')}"'''
replacement = '''            normalized_path = path_str.replace('/', '\\\\')
            return f"{self._server_path}\\\\{normalized_path}"'''
text = replace_checked(text, needle, replacement)
smb.write_text(text, encoding="utf-8")

security = root / "app/core/security.py"
text = security.read_text(encoding="utf-8")
needle = "    if jwt_token:\n"
legacy_replacement = "    if os.getenv(\"MOVIEPILOT_NO_AUTH\") == \"1\":\n        return schemas.TokenPayload(sub=0, username=settings.SUPERUSER, super_user=True, level=99, purpose=\"authentication\")\n    if jwt_token:\n"
replacement = "    if os.getenv(\"MOVIEPILOT_NO_AUTH\") == \"1\":\n        from app.helper.sites import SitesHelper  # noqa\n        return schemas.TokenPayload(sub=0, username=settings.SUPERUSER, super_user=True, level=SitesHelper().auth_level, purpose=\"authentication\")\n    if jwt_token:\n"
if legacy_replacement in text:
    text = text.replace(legacy_replacement, replacement, 1)
elif replacement not in text:
    text = replace_checked(text, needle, replacement)

needle = "    # 验证并解析资源访问令牌\n    return __verify_token(token=resource_token, purpose=\"resource\")"
replacement = "    if os.getenv(\"MOVIEPILOT_NO_AUTH\") == \"1\":\n        return __create_superuser_token_payload()\n    # 验证并解析资源访问令牌\n    return __verify_token(token=resource_token, purpose=\"resource\")"
if replacement not in text:
    if needle not in text:
        raise RuntimeError("MoviePilot resource-token patch target was not found")
    text = text.replace(needle, replacement, 1)
security.write_text(text, encoding="utf-8")

user_oper = root / "app/db/user_oper.py"
text = user_oper.read_text(encoding="utf-8")
text = replace_checked(text, "from app.core.security import verify_token\n", "from app.core.security import verify_token\nfrom app.core.config import settings\nimport os\n")
text = replace_checked(text, "    user = User.get(db, rid=token_data.sub)\n", "    if os.getenv(\"MOVIEPILOT_NO_AUTH\") == \"1\":\n        return User(id=0, name=settings.SUPERUSER, is_active=True, is_superuser=True, permissions={})\n    user = User.get(db, rid=token_data.sub)\n")
text = replace_checked(text, "    user = await User.async_get(db, rid=token_data.sub)\n", "    if os.getenv(\"MOVIEPILOT_NO_AUTH\") == \"1\":\n        return User(id=0, name=settings.SUPERUSER, is_active=True, is_superuser=True, permissions={})\n    user = await User.async_get(db, rid=token_data.sub)\n")
user_oper.write_text(text, encoding="utf-8")

login = root / "app/api/endpoints/login.py"
text = login.read_text(encoding="utf-8")
needle = "    success, user_or_message = UserChain().user_authenticate(\n"
legacy_replacement = "    if os.getenv(\"MOVIEPILOT_NO_AUTH\") == \"1\":\n        access_token = security.create_access_token(userid=0, username=settings.SUPERUSER, super_user=True, expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))\n        return schemas.Token(access_token=access_token, token_type=\"bearer\", super_user=True, user_id=0, user_name=settings.SUPERUSER, level=99, permissions={}, wizard=False)\n\n    success, user_or_message = UserChain().user_authenticate(\n"
replacement = "    if os.getenv(\"MOVIEPILOT_NO_AUTH\") == \"1\":\n        level = SitesHelper().auth_level\n        access_token = security.create_access_token(userid=0, username=settings.SUPERUSER, super_user=True, expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES), level=level)\n        return schemas.Token(access_token=access_token, token_type=\"bearer\", super_user=True, user_id=0, user_name=settings.SUPERUSER, level=level, permissions={}, wizard=False)\n\n    success, user_or_message = UserChain().user_authenticate(\n"
text = replace_checked(text, "from datetime import timedelta\n", "from datetime import timedelta\nimport os\n")
if legacy_replacement in text:
    text = text.replace(legacy_replacement, replacement, 1)
elif replacement not in text:
    text = replace_checked(text, needle, replacement)
login.write_text(text, encoding="utf-8")

bangumi = root / "app/modules/bangumi/bangumi.py"
text = bangumi.read_text(encoding="utf-8")
sync_needle = "        resp = self._req.get_res(url=req_url, params=params)"
sync_replacement = "        self._req = RequestUtils(\n            ua=settings.NORMAL_USER_AGENT,\n            proxies=settings.PROXY,\n            session=self._session,\n        )\n        resp = self._req.get_res(url=req_url, params=params)"
if sync_replacement not in text:
    if sync_needle not in text:
        raise RuntimeError("MoviePilot Bangumi sync proxy patch target was not found")
    text = text.replace(sync_needle, sync_replacement, 1)
async_needle = "        resp = await self._async_req.get_res(url=req_url, params=params)"
async_replacement = "        self._async_req = AsyncRequestUtils(\n            ua=settings.NORMAL_USER_AGENT,\n            proxies=settings.PROXY,\n        )\n        resp = await self._async_req.get_res(url=req_url, params=params)"
if async_replacement not in text:
    if async_needle not in text:
        raise RuntimeError("MoviePilot Bangumi async proxy patch target was not found")
    text = text.replace(async_needle, async_replacement, 1)
bangumi.write_text(text, encoding="utf-8")
