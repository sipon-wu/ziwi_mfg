import bcrypt

# NOTE: 直接使用 bcrypt，不依赖 passlib。
# 原因：passlib 1.7.4 与 bcrypt>=4.1（已移除 bcrypt.__about__）不兼容，
# 会导致 CryptContext 后端加载失败、注册时抛 "password cannot be longer than 72 bytes"。
# bcrypt 对密码明文上限 72 字节，超出部分会被静默截断；此处显式截断以保持行为确定。


def hash_password(password: str) -> str:
    pw = password.encode("utf-8")
    if len(pw) > 72:
        pw = pw[:72]
    return bcrypt.hashpw(pw, bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"),
            hashed_password.encode("utf-8"),
        )
    except (ValueError, TypeError):
        return False
