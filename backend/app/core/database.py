# SQLAlchemy async engine + session factory
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from app.core.config import get_settings
from functools import lru_cache

settings = get_settings()

@lru_cache()
def get_engine():
    url = settings.DATABASE_URL
    if "sqlite" in url:
        return create_async_engine(url, echo=settings.DB_ECHO_SQL)
    return create_async_engine(
        url,
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
        echo=settings.DB_ECHO_SQL,
    )

engine = None  # Lazy init

def ensure_engine():
    global engine
    if engine is None:
        engine = get_engine()
    return engine

async_session_factory = None

def get_session_factory():
    global async_session_factory
    if async_session_factory is None:
        eng = ensure_engine()
        async_session_factory = async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)
    return async_session_factory

class Base(DeclarativeBase):
    pass

async def get_db():
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

async def init_db():
    eng = ensure_engine()
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
