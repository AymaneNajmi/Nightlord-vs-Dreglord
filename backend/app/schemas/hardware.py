from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field


class SpecTech(BaseModel):
    feature: str = ""
    valeur: str = ""


class SpecPhys(BaseModel):
    spec: str = ""
    valeur: str = ""


class Licensing(BaseModel):
    network_essentials: str = ""
    network_advantage: str = ""
    dna_essentials: str = ""
    dna_advantage: str = ""
    delivery_model: str = ""


class UplinkModule(BaseModel):
    module_id: str = ""
    description: str = ""


class PowerSupply(BaseModel):
    model: str = ""
    wattage: str = ""
    btu_hr: str = ""
    input_voltage: str = ""
    input_current: str = ""
    output_ratings: str = ""
    hold_up_time: str = ""
    input_receptacles: str = ""
    cord_rating: str = ""
    dimensions: str = ""
    weight: str = ""
    operating_temp: str = ""
    storage_temp: str = ""
    humidity: str = ""
    altitude: str = ""
    led_indicators: str = ""


class StackwiseInfo(BaseModel):
    technology: str = ""
    stackpower_supported: str = ""
    max_members: str = ""
    bandwidth: str = ""
    compatibility: str = ""
    restrictions: str = ""


class PerformanceMetric(BaseModel):
    metric: str = ""
    value: str = ""


class HardwareOutput(BaseModel):
    description_generale: str = ""
    specs_techniques: List[SpecTech] = Field(default_factory=list)
    specs_physiques: List[SpecPhys] = Field(default_factory=list)
    fonctionnalites: List[str] = Field(default_factory=list)
    aspect_fonctionnel: str = ""
    licensing: Licensing = Field(default_factory=Licensing)
    uplink_modules: List[UplinkModule] = Field(default_factory=list)
    power_supplies: List[PowerSupply] = Field(default_factory=list)
    stackwise_info: StackwiseInfo = Field(default_factory=StackwiseInfo)
    performance_scalability: List[PerformanceMetric] = Field(default_factory=list)
    datasheet_url: str = ""
    image_url: str = ""
