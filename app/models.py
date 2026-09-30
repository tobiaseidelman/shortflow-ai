from sqlalchemy.orm import Mapped,mapped_column
from sqlalchemy import String,Float,Integer,DateTime,Text,ForeignKey
from datetime import datetime
from .db import Base
class BackgroundVideo(Base):
 __tablename__='background_videos'; id:Mapped[int]=mapped_column(primary_key=True); name:Mapped[str]=mapped_column(String(255)); path:Mapped[str]=mapped_column(Text); duration:Mapped[float]=mapped_column(Float,default=0); width:Mapped[int]=mapped_column(Integer,default=0); height:Mapped[int]=mapped_column(Integer,default=0); size:Mapped[int]=mapped_column(Integer,default=0); status:Mapped[str]=mapped_column(String(40),default='pending'); created_at:Mapped[datetime]=mapped_column(DateTime,default=datetime.utcnow)
class Clip(Base):
 __tablename__='clips'; id:Mapped[int]=mapped_column(primary_key=True); source_video_id:Mapped[int]=mapped_column(ForeignKey('background_videos.id')); start_time:Mapped[float]=mapped_column(Float); end_time:Mapped[float]=mapped_column(Float); duration:Mapped[float]=mapped_column(Float); motion_score:Mapped[float]=mapped_column(Float); visual_change_score:Mapped[float]=mapped_column(Float); action_onset:Mapped[float]=mapped_column(Float); quality_score:Mapped[float]=mapped_column(Float); hook_score:Mapped[float]=mapped_column(Float); loop_score:Mapped[float]=mapped_column(Float); times_used:Mapped[int]=mapped_column(Integer,default=0); last_used:Mapped[datetime|None]=mapped_column(DateTime,nullable=True); cooldown_until:Mapped[int]=mapped_column(Integer,default=0); similarity_group:Mapped[str]=mapped_column(String(64),default=''); attention_curve:Mapped[str]=mapped_column(Text,default='[]')
class Story(Base):
 __tablename__='stories'; id:Mapped[int]=mapped_column(primary_key=True); genre:Mapped[str]=mapped_column(String(40)); duration_target:Mapped[int]=mapped_column(Integer); title:Mapped[str]=mapped_column(String(255)); text:Mapped[str]=mapped_column(Text); created_at:Mapped[datetime]=mapped_column(DateTime,default=datetime.utcnow)
class Short(Base):
 __tablename__='shorts'; id:Mapped[int]=mapped_column(primary_key=True); story_id:Mapped[int|None]=mapped_column(ForeignKey('stories.id'),nullable=True); duration:Mapped[float]=mapped_column(Float); status:Mapped[str]=mapped_column(String(40)); output_path:Mapped[str|None]=mapped_column(Text,nullable=True); sequence_json:Mapped[str]=mapped_column(Text,default='[]'); created_at:Mapped[datetime]=mapped_column(DateTime,default=datetime.utcnow)
class UsedClip(Base):
 __tablename__='used_clips'; id:Mapped[int]=mapped_column(primary_key=True); clip_id:Mapped[int]=mapped_column(ForeignKey('clips.id')); short_id:Mapped[int]=mapped_column(ForeignKey('shorts.id')); position:Mapped[int]=mapped_column(Integer); used_at:Mapped[datetime]=mapped_column(DateTime,default=datetime.utcnow)
class ImportSource(Base):
 __tablename__='import_sources'; id:Mapped[int]=mapped_column(primary_key=True); url:Mapped[str]=mapped_column(Text); platform:Mapped[str]=mapped_column(String(60)); rights_declared_at:Mapped[datetime]=mapped_column(DateTime); status:Mapped[str]=mapped_column(String(60)); created_at:Mapped[datetime]=mapped_column(DateTime,default=datetime.utcnow)

class StoryGeneration(Base):
    __tablename__ = 'story_generations'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    theme: Mapped[str] = mapped_column(Text)
    duration: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(255), default='')
    status: Mapped[str] = mapped_column(String(20))
    message: Mapped[str] = mapped_column(Text, default='')
    part1_id: Mapped[int | None] = mapped_column(ForeignKey('stories.id'), nullable=True)
    part2_id: Mapped[int | None] = mapped_column(ForeignKey('stories.id'), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class VideoImportJob(Base):
    __tablename__ = 'video_import_jobs'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey('import_sources.id'))
    video_id: Mapped[int | None] = mapped_column(ForeignKey('background_videos.id'), nullable=True)
    status: Mapped[str] = mapped_column(String(20))
    message: Mapped[str] = mapped_column(Text, default='')
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class RenderJob(Base):
    __tablename__ = 'render_jobs'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    status: Mapped[str] = mapped_column(String(20))
    message: Mapped[str] = mapped_column(Text, default='')
    story_ids: Mapped[str] = mapped_column(Text)
    short_ids: Mapped[str] = mapped_column(Text, default='[]')
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class NarrationAsset(Base):
    __tablename__ = 'narration_assets'
    short_id: Mapped[int] = mapped_column(ForeignKey('shorts.id'), primary_key=True)
    audio_path: Mapped[str] = mapped_column(Text)
    subtitle_path: Mapped[str] = mapped_column(Text)
    text_snapshot: Mapped[str] = mapped_column(Text)


class UploadJob(Base):
    __tablename__ = 'upload_jobs'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    size: Mapped[int] = mapped_column(Integer)
    received: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default='uploading')
    message: Mapped[str] = mapped_column(Text, default='Subiendo archivo…')
    video_id: Mapped[int | None] = mapped_column(ForeignKey('background_videos.id'), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
