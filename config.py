from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    DISCORD_TOKEN: str
    RIOT_API_KEY: str
    MONGO_URI: str
    MONGO_DB_NAME: str = "league_tracker"
    LOG_LEVEL: str = "INFO"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

settings = Settings()

# Static Mappings Expanded
PLATFORM_MAP = {
    "na": "na1", "euw": "euw1", "eune": "eun1", "kr": "kr", "oce": "oc1",
    "jp": "jp1", "br": "br1", "las": "la2", "lan": "la1", "tr": "tr1",
    "ru": "ru", "ph": "ph2", "sg": "sg2", "th": "th2", "tw": "tw2", "vn": "vn2", "me": "me1"
}

CLUSTER_MAP = {
    "na": "americas", "br": "americas", "las": "americas", "lan": "americas",
    "euw": "europe", "eune": "europe", "tr": "europe", "ru": "europe", "me": "europe",
    "kr": "asia", "jp": "asia",
    "oce": "sea", "ph": "sea", "sg": "sea", "th": "sea", "tw": "sea", "vn": "sea"
}

MATCH_REGION_MAP = {
    "na1": "americas", "br1": "americas", "la1": "americas", "la2": "americas",
    "euw1": "europe", "eun1": "europe", "tr1": "europe", "ru": "europe", "me1": "europe",
    "kr": "asia", "jp1": "asia",
    "oc1": "sea", "ph2": "sea", "sg2": "sea", "th2": "sea", "tw2": "sea", "vn2": "sea"
}

QUEUE_ID_MAP = {
    400: "Draft Pick",
    420: "Ranked Solo/Duo",
    430: "Blind Pick",
    440: "Ranked Flex",
    450: "ARAM",
    490: "Quickplay",
    700: "Clash",
    1700: "Arena",
    2400: "ARAM Mayhem"
}

QUEUE_SOLO = 420