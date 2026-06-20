from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import desc

from app.db.session import SessionLocal
from app.models.climate import District, WeatherData, SatelliteData, RiskScore, Prediction, ClimateAlert


def map_to_dict(weather: WeatherData, satellite: SatelliteData) -> dict:
    return {
        "observed_on": weather.observed_on,
        "rainfall_mm": weather.rainfall_mm,
        "rainfall_deficit_pct": weather.rainfall_deficit_pct,
        "temperature_c": weather.temperature_c,
        "humidity_pct": weather.humidity_pct,
        "river_level_m": weather.river_level_m,
        "soil_moisture_pct": weather.soil_moisture_pct,
        "aqi": weather.aqi,
        "ndvi": satellite.ndvi,
        "land_surface_temp_c": satellite.land_surface_temp_c,
        "water_body_index": satellite.water_body_index,
        "reservoir_level_pct": satellite.reservoir_level_pct,
    }


class ClimateDataGateway:
    """Production integration boundary for national climate data providers powered by PostgreSQL."""

    def fetch_imd_weather(self, district_code: str) -> list[dict]:
        with SessionLocal() as db:
            district = db.query(District).filter(District.code == district_code).first()
            if not district:
                raise HTTPException(status_code=404, detail="District not found")
            
            rows = (
                db.query(WeatherData, SatelliteData)
                .join(
                    SatelliteData,
                    (SatelliteData.district_id == WeatherData.district_id)
                    & (SatelliteData.observed_on == WeatherData.observed_on),
                )
                .filter(WeatherData.district_id == district.id)
                .order_by(WeatherData.observed_on.asc())
                .all()
            )
            if not rows:
                raise HTTPException(status_code=404, detail="No weather/satellite data found for this district")
            
            return [map_to_dict(w, s) for w, s in rows]

    def fetch_nrsc_satellite(self, district_code: str) -> list[dict]:
        return self.fetch_imd_weather(district_code)

    def fetch_bhuvan_boundary(self, district_code: str) -> dict:
        with SessionLocal() as db:
            district = db.query(District).filter(District.code == district_code).first()
            if not district:
                raise HTTPException(status_code=404, detail="District not found")
            return {
                "provider": "ISRO Bhuvan",
                "district_code": district_code,
                "centroid": [district.centroid_lon, district.centroid_lat],
                "geometry": district.boundary_geojson,
            }

    def fetch_wris_reservoirs(self, district_code: str) -> dict:
        weather_list = self.fetch_imd_weather(district_code)
        if not weather_list:
            raise HTTPException(status_code=404, detail="No reservoir data found for this district")
        latest = weather_list[-1]
        return {
            "provider": "India-WRIS",
            "reservoir_level_pct": latest["reservoir_level_pct"],
            "major_reservoirs": [
                {"name": "Integrated Basin Storage", "level_pct": latest["reservoir_level_pct"]}
            ],
        }

    def fetch_cpcb_aqi(self, district_code: str) -> dict:
        weather_list = self.fetch_imd_weather(district_code)
        if not weather_list:
            raise HTTPException(status_code=404, detail="No AQI data found for this district")
        latest = weather_list[-1]
        return {"provider": "CPCB", "aqi": latest["aqi"]}

    def fetch_risk_scores(self, district_code: str) -> dict:
        with SessionLocal() as db:
            district = db.query(District).filter(District.code == district_code).first()
            if not district:
                raise HTTPException(status_code=404, detail="District not found")
            risk = db.query(RiskScore).filter(RiskScore.district_id == district.id).order_by(desc(RiskScore.valid_on)).first()
            if not risk:
                raise HTTPException(status_code=404, detail="No risk score data found for this district")
            return {
                "flood_risk": risk.flood_risk,
                "drought_risk": risk.drought_risk,
                "heatwave_risk": risk.heatwave_risk,
                "water_stress_risk": risk.water_stress_risk,
                "composite_risk": risk.composite_risk,
                "trend": risk.trend,
            }

    def fetch_predictions(self, district_code: str) -> list[dict]:
        with SessionLocal() as db:
            district = db.query(District).filter(District.code == district_code).first()
            if not district:
                raise HTTPException(status_code=404, detail="District not found")
            predictions = db.query(Prediction).filter(Prediction.district_id == district.id).order_by(desc(Prediction.valid_for)).limit(10).all()
            return [
                {
                    "prediction_type": p.prediction_type,
                    "probability": p.probability,
                    "risk_zone": p.risk_zone,
                    "valid_for": p.valid_for.isoformat() if p.valid_for else None,
                    "model_name": p.model_name,
                }
                for p in predictions
            ]

    def fetch_alerts(self, district_code: str) -> list[dict]:
        with SessionLocal() as db:
            district = db.query(District).filter(District.code == district_code).first()
            if not district:
                raise HTTPException(status_code=404, detail="District not found")
            alerts = db.query(ClimateAlert).filter(ClimateAlert.district_id == district.id).order_by(desc(ClimateAlert.issued_at)).limit(5).all()
            return [
                {
                    "severity": a.severity,
                    "alert_type": a.alert_type,
                    "title": a.title,
                    "message": a.message,
                    "issued_at": a.issued_at.isoformat() if a.issued_at else None,
                }
                for a in alerts
            ]

    def _district(self, district_code: str) -> dict:
        with SessionLocal() as db:
            district = db.query(District).filter(District.code == district_code).first()
            if not district:
                raise HTTPException(status_code=404, detail="District not found")
            return {
                "id": district.id,
                "state_id": district.state_id,
                "name": district.name,
                "district_code": district.code,
                "population": district.population,
                "area": district.area_sq_km,
                "lat": district.centroid_lat,
                "lon": district.centroid_lon,
                "geometry": district.boundary_geojson,
            }
