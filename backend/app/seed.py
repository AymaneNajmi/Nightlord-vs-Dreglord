import logging
from app.core.db import SessionLocal, engine, Base
from app.models.user import User, Role
from app.core.config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def seed_db():
    logger.info("Ensuring database tables exist...")
    Base.metadata.create_all(bind=engine)
    
    db = SessionLocal()
    try:
        # Seed Admin
        admin = db.query(User).filter(User.email == settings.ADMIN_EMAIL).first()
        if not admin:
            admin_user = User(
                email=settings.ADMIN_EMAIL,
                full_name="System Admin",
                password=settings.ADMIN_PASSWORD,
                role=Role.ADMIN,
                is_active=True
            )
            db.add(admin_user)
            logger.info(f"Admin user seeded with email {settings.ADMIN_EMAIL}")
        else:
            logger.info("Admin user already exists.")

        # Seed User
        user = db.query(User).filter(User.email == settings.USER_EMAIL).first()
        if not user:
            normal_user = User(
                email=settings.USER_EMAIL,
                full_name="Standard User",
                password=settings.USER_PASSWORD,
                role=Role.USER,
                is_active=True
            )
            db.add(normal_user)
            logger.info(f"Normal user seeded with email {settings.USER_EMAIL}")
        else:
            logger.info("Normal user already exists.")

        db.commit()
    except Exception as e:
        logger.error(f"Error seeding database: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    logger.info("Starting DB seed script...")
    seed_db()
    logger.info("DB seed completed.")
