from pydantic_settings import BaseSettings
from typing import List, Union


class Settings(BaseSettings):
    bot_token: str
    admin_telegram_ids: Union[List[int], int] = []
    order_chat_id: int = -1004309485623
    database_url: str
    web_admin_user: str = "admin"
    web_admin_password: str = "admin123"
    web_admin_host: str = "0.0.0.0"
    web_admin_port: int = 8000
    
    # Proxy configuration (optional)
    proxy_host: str = ""
    proxy_port: int = 0
    proxy_secret: str = ""

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

    @property
    def admin_ids_list(self) -> List[int]:
        if isinstance(self.admin_telegram_ids, int):
            return [self.admin_telegram_ids]
        return self.admin_telegram_ids


settings = Settings()
