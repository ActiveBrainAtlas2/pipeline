from datetime import datetime
from sqlalchemy.sql import func
from sqlalchemy import Column, String, Integer, ForeignKey, DateTime, Boolean, TIMESTAMP
from sqlalchemy.sql.expression import null
from sqlalchemy.sql.sqltypes import Float
from .atlas_model import Base, AtlasModel



class LayerData(Base, AtlasModel):
    __tablename__ = 'layer_data'
    id =  Column(Integer, primary_key=True, nullable=False)
    url_id = Column(Integer, nullable=False)
    prep_id = Column(String, nullable=False)
    layer = Column(String, nullable=False)
    x = Column(Float, nullable=False)
    y = Column(Float, nullable=False)
    section = Column(Float, nullable=False)

    updated = Column(TIMESTAMP)





