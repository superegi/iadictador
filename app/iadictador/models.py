from datetime import datetime, timezone
from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text, JSON, UniqueConstraint, Index, text, func
from sqlalchemy.orm import relationship

from .db import Base
from .security import now_utc


class User(Base):
    __tablename__ = "iad_users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(80), unique=True, nullable=False, index=True)
    email = Column(String(255), nullable=True, index=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(20), nullable=False, default="user")
    is_active = Column(Boolean, nullable=False, default=True)
    must_change_password = Column(Boolean, nullable=False, default=True)

    first_name = Column(String(120), nullable=True)
    last_name = Column(String(120), nullable=True)
    country = Column(String(120), nullable=True)
    timezone = Column(String(120), nullable=True)
    specialty = Column(String(120), nullable=True)
    subspecialty = Column(String(120), nullable=True)
    birthdate = Column(String(20), nullable=True)

    billing_visible = Column(Boolean, nullable=False, default=False)
    billing_enabled = Column(Boolean, nullable=False, default=False)
    price_per_transcription = Column(Float, nullable=True)

    created_at = Column(DateTime(timezone=True), default=now_utc, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=now_utc, onupdate=now_utc, nullable=False)
    last_login_at = Column(DateTime(timezone=True), nullable=True)
    last_login_ip = Column(String(80), nullable=True)
    last_login_user_agent = Column(Text, nullable=True)

    work_orders = relationship("WorkOrder", back_populates="user")


class Workplace(Base):
    __tablename__ = "iad_workplaces"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False, unique=True)
    kind = Column(String(80), nullable=True)
    city = Column(String(120), nullable=True)
    country = Column(String(120), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), default=now_utc, nullable=False)
    tariffs_json = Column(String, nullable=True)

class ReportTemplate(Base):
    __tablename__ = "iad_report_templates"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("iad_users.id"), nullable=True)
    is_global = Column(Boolean, nullable=False, default=False)
    is_shared = Column(Boolean, default=False, nullable=False)
    imported_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=True)
    import_source = Column(String, nullable=True)


    radiology_use = Column(String(20), nullable=False)
    body_region = Column(String, nullable=True)
    template_name = Column(String(255), nullable=False)
    title = Column(String(255), nullable=True)
    technique = Column(Text, nullable=True)
    background = Column(Text, nullable=True)
    findings = Column(Text, nullable=True)
    impression = Column(Text, nullable=True)
    tags = Column(Text, nullable=True)
    specific_rules_json = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), default=now_utc, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=now_utc, onupdate=now_utc, nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "template_name", name="uq_iad_template_user_name"),
    )


class WorkOrder(Base):
    __tablename__ = "iad_work_orders"

    id = Column(Integer, primary_key=True, index=True)
    ot_user_number = Column(Integer, nullable=False, index=True)

    user_id = Column(Integer, ForeignKey("iad_users.id"), nullable=False, index=True)
    workplace_id = Column(Integer, ForeignKey("iad_workplaces.id"), nullable=True)
    template_id = Column(Integer, ForeignKey("iad_report_templates.id"), nullable=True)

    status = Column(String(40), nullable=False, default="draft")

    ip = Column(String(80), nullable=True)
    device = Column(String(120), nullable=True)
    user_agent = Column(Text, nullable=True)
    timezone = Column(String(120), nullable=True)
    utc_offset_minutes = Column(Integer, nullable=True)

    input_type = Column(String(40), nullable=True)
    input_text_final = Column(Text, nullable=True)
    audio_transcription_initial = Column(Text, nullable=True)
    audio_transcription_final = Column(Text, nullable=True)
    clarification_text = Column(Text, nullable=True)

    review_report = Column(Text, nullable=True)
    final_report_initial = Column(Text, nullable=True)
    final_report_accepted = Column(Text, nullable=True)
    final_report_diff = Column(Text, nullable=True)

    patient_first_name = Column(String(120), nullable=True)
    patient_last_name = Column(String(120), nullable=True)
    patient_sex = Column(String(40), nullable=True)
    patient_birthdate = Column(String(20), nullable=True)
    patient_age = Column(String(20), nullable=True)
    hospital_service = Column(String(255), nullable=True)
    report_type = Column(String(80), nullable=True)
    modality = Column(String(20), nullable=True)
    report_title = Column(String(255), nullable=True)

    billing_visible = Column(Boolean, nullable=False, default=False)
    billing_enabled = Column(Boolean, nullable=False, default=False)
    charge_yes_no = Column(Boolean, nullable=False, default=False)
    charge_value = Column(Float, nullable=True)

    created_at = Column(DateTime(timezone=True), default=now_utc, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=now_utc, onupdate=now_utc, nullable=False)
    validated_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User", back_populates="work_orders")


class OTAudioFile(Base):
    __tablename__ = "iad_ot_audio_files"

    id = Column(Integer, primary_key=True, index=True)
    ot_id = Column(Integer, ForeignKey("iad_work_orders.id"), nullable=False, index=True)
    audio_order = Column(Integer, nullable=False, default=1)
    original_filename = Column(String(255), nullable=True)
    stored_path = Column(Text, nullable=False)
    mime_type = Column(String(120), nullable=True)
    extension = Column(String(40), nullable=True)
    duration_seconds = Column(Float, nullable=True)
    transcription_raw = Column(Text, nullable=True)
    transcription_edited = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=now_utc, nullable=False)


class AuditLog(Base):
    __tablename__ = "iad_audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("iad_users.id"), nullable=True, index=True)
    action = Column(String(120), nullable=False)
    detail = Column(Text, nullable=True)
    ip = Column(String(80), nullable=True)
    user_agent = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=now_utc, nullable=False)
