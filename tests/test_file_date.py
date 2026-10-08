from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.routes_files import FileDateUpdate, update_file_date
from app.db.database import Base
from app.db.models import File
from app.db.repositories import update_file_created_at


def test_user_edited_file_date_survives_regular_date_update():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    file_record = File(
        id="file-1",
        sha256="a" * 64,
        original_filename="document.pdf",
        archive_path="document.pdf",
        created_at="2024-01-01",
    )
    db.add(file_record)
    db.commit()

    response = update_file_date(
        file_record.id,
        FileDateUpdate(date=date(2024, 6, 15)),
        db,
    )
    assert response["created_at"] == "2024-06-15"

    update_file_created_at(db, file_record.id, "2024-01-01")

    updated = db.get(File, file_record.id)
    assert updated is not None
    assert updated.created_at == "2024-06-15"
    assert updated.created_at_user_edited is True
