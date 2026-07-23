import sys
from pathlib import Path

root = Path(sys.argv[1])

security = root / "app/core/security.py"
text = security.read_text(encoding="utf-8")
needle = "    if jwt_token:\n"
replacement = "    if os.getenv(\"MOVIEPILOT_NO_AUTH\") == \"1\":\n        return schemas.TokenPayload(sub=0, username=settings.SUPERUSER, super_user=True, level=99, purpose=\"authentication\")\n    if jwt_token:\n"
if replacement not in text:
    text = text.replace(needle, replacement, 1)
security.write_text(text, encoding="utf-8")

user_oper = root / "app/db/user_oper.py"
text = user_oper.read_text(encoding="utf-8")
text = text.replace("from app.core.security import verify_token\n", "from app.core.security import verify_token\nfrom app.core.config import settings\nimport os\n", 1)
text = text.replace("    user = User.get(db, rid=token_data.sub)\n", "    if os.getenv(\"MOVIEPILOT_NO_AUTH\") == \"1\":\n        return User(id=0, name=settings.SUPERUSER, is_active=True, is_superuser=True, permissions={})\n    user = User.get(db, rid=token_data.sub)\n", 1)
text = text.replace("    user = await User.async_get(db, rid=token_data.sub)\n", "    if os.getenv(\"MOVIEPILOT_NO_AUTH\") == \"1\":\n        return User(id=0, name=settings.SUPERUSER, is_active=True, is_superuser=True, permissions={})\n    user = await User.async_get(db, rid=token_data.sub)\n", 1)
user_oper.write_text(text, encoding="utf-8")

login = root / "app/api/endpoints/login.py"
text = login.read_text(encoding="utf-8")
needle = "    success, user_or_message = UserChain().user_authenticate(\n"
replacement = "    if os.getenv(\"MOVIEPILOT_NO_AUTH\") == \"1\":\n        access_token = security.create_access_token(userid=0, username=settings.SUPERUSER, super_user=True, expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))\n        return schemas.Token(access_token=access_token, token_type=\"bearer\", super_user=True, user_id=0, user_name=settings.SUPERUSER, level=99, permissions={}, wizard=False)\n\n    success, user_or_message = UserChain().user_authenticate(\n"
text = text.replace("from datetime import timedelta\n", "from datetime import timedelta\nimport os\n", 1)
text = text.replace(needle, replacement, 1)
login.write_text(text, encoding="utf-8")
