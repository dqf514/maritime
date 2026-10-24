from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings

settings = get_settings()
_is_sqlite = settings.database_url.startswith("sqlite")

# SQLite：FastAPI 的同步路由跑在 anyio 线程池 → 必须关掉同线程检查；
# 另外给一个 30s 的锁等待（默认 5s），否则并发写会直接抛
# "database is locked"（开发期偶发 500 的头号原因，P2-8）。
connect_args: dict = {"check_same_thread": False, "timeout": 30} if _is_sqlite else {}

engine_kwargs: dict = {"pool_pre_ping": True, "connect_args": connect_args}
if not _is_sqlite:
    # Postgres：显式给连接池参数，别吃 SQLAlchemy 的默认值
    # （pool_size=5 / max_overflow=10，RDS 上很容易打满；且长连接不
    # recycle 会被云防火墙静默掐断 —— 表现为"跑一夜后突然全 500"）。
    engine_kwargs.update(
        pool_size=int(settings.db_pool_size),
        max_overflow=int(settings.db_max_overflow),
        pool_timeout=float(settings.db_pool_timeout),
        pool_recycle=int(settings.db_pool_recycle),
        pool_pre_ping=True,
    )

engine = create_engine(settings.database_url, **engine_kwargs)

if _is_sqlite:
    # ⚠️ SQLite **默认不强制外键**（`PRAGMA foreign_keys` 默认 OFF），
    # 而 Postgres 一直强制 —— 于是开发库能写入"孤儿行"，生产库会报错，
    # 行为在两个环境之间分叉（P2「SQLite / PG 配置差异」）。
    # 每个新连接都要显式打开（PRAGMA 是**连接级**设置，不是库级）。
    from sqlalchemy import event

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _record):  # noqa: ANN001
        cur = dbapi_conn.cursor()
        try:
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA synchronous=NORMAL")
        finally:
            cur.close()

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
