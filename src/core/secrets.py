"""Secrets management for secure credential handling.

Provides secure storage and retrieval of sensitive configuration
like API keys, passwords, and tokens.
"""

import base64
import hashlib
import os
from dataclasses import dataclass
from typing import Any

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from src.core.logging_config import get_logger

logger = get_logger("secrets")


class SecretsManager:
    """Manager for encrypted secrets storage.
    
    Uses Fernet symmetric encryption with PBKDF2 key derivation.
    Secrets are encrypted at rest and decrypted on demand.
    """
    
    def __init__(self, master_key: str | None = None):
        """Initialize secrets manager.
        
        Args:
            master_key: Master encryption key (or from env var)
        """
        self._secrets: dict[str, str] = {}
        self._fernet: Fernet | None = None
        
        # Get master key from environment or parameter
        key = master_key or os.environ.get("WTI_SECRETS_MASTER_KEY")
        
        if key:
            self._fernet = self._create_fernet(key)
            logger.info("Secrets manager initialized with encryption")
        else:
            logger.warning(
                "Secrets manager initialized without encryption - "
                "set WTI_SECRETS_MASTER_KEY for secure storage"
            )
    
    def _create_fernet(self, master_key: str) -> Fernet:
        """Create Fernet instance from master key.
        
        Args:
            master_key: Master encryption key
            
        Returns:
            Fernet instance
        """
        # Derive key using PBKDF2
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=hashlib.sha256(b"wti-trading-bot").digest(),
            iterations=480000,
        )
        
        key = base64.urlsafe_b64encode(kdf.derive(master_key.encode()))
        return Fernet(key)
    
    def set_secret(self, name: str, value: str) -> None:
        """Store a secret.
        
        Args:
            name: Secret name
            value: Secret value
        """
        if self._fernet:
            # Encrypt the value
            encrypted = self._fernet.encrypt(value.encode())
            self._secrets[name] = encrypted.decode()
        else:
            # Store plaintext (not recommended for production)
            self._secrets[name] = value
        
        logger.debug("Secret stored", name=name)
    
    def get_secret(self, name: str, default: str | None = None) -> str | None:
        """Retrieve a secret.
        
        Args:
            name: Secret name
            default: Default value if not found
            
        Returns:
            Secret value or default
        """
        if name not in self._secrets:
            return default
        
        value = self._secrets[name]
        
        if self._fernet:
            try:
                # Decrypt the value
                decrypted = self._fernet.decrypt(value.encode())
                return decrypted.decode()
            except Exception as e:
                logger.error("Failed to decrypt secret", name=name, error=str(e))
                return default
        
        return value
    
    def delete_secret(self, name: str) -> bool:
        """Delete a secret.
        
        Args:
            name: Secret name
            
        Returns:
            True if deleted
        """
        if name in self._secrets:
            del self._secrets[name]
            logger.debug("Secret deleted", name=name)
            return True
        return False
    
    def rotate_key(self, new_master_key: str) -> None:
        """Rotate encryption key.
        
        Re-encrypts all secrets with new key.
        
        Args:
            new_master_key: New master encryption key
        """
        if not self._fernet:
            logger.warning("No encryption active, setting new key")
            self._fernet = self._create_fernet(new_master_key)
            return
        
        # Decrypt all secrets with old key
        decrypted = {}
        for name, value in self._secrets.items():
            try:
                decrypted[name] = self._fernet.decrypt(value.encode()).decode()
            except Exception as e:
                logger.error("Failed to decrypt during rotation", name=name, error=str(e))
        
        # Create new Fernet with new key
        self._fernet = self._create_fernet(new_master_key)
        
        # Re-encrypt with new key
        self._secrets.clear()
        for name, value in decrypted.items():
            self.set_secret(name, value)
        
        logger.info("Encryption key rotated successfully")
    
    def list_secrets(self) -> list[str]:
        """List all secret names.
        
        Returns:
            List of secret names (not values)
        """
        return list(self._secrets.keys())
    
    def export_secrets(self) -> dict[str, str]:
        """Export all secrets (encrypted).
        
        Returns:
            Dictionary of encrypted secrets
        """
        return self._secrets.copy()
    
    def import_secrets(self, secrets: dict[str, str]) -> None:
        """Import secrets (encrypted).
        
        Args:
            secrets: Dictionary of encrypted secrets
        """
        self._secrets.update(secrets)
        logger.info("Secrets imported", count=len(secrets))
    
    def clear(self) -> None:
        """Clear all secrets."""
        self._secrets.clear()
        logger.info("All secrets cleared")


class EnvironmentSecretsLoader:
    """Load secrets from environment variables."""
    
    SECRET_PREFIX = "WTI_SECRET_"
    
    @classmethod
    def load(cls, secrets_manager: SecretsManager) -> int:
        """Load secrets from environment.
        
        Args:
            secrets_manager: Secrets manager instance
            
        Returns:
            Number of secrets loaded
        """
        count = 0
        
        for key, value in os.environ.items():
            if key.startswith(cls.SECRET_PREFIX):
                # Convert WTI_SECRET_API_KEY -> api_key
                secret_name = key[len(cls.SECRET_PREFIX):].lower()
                secrets_manager.set_secret(secret_name, value)
                count += 1
        
        logger.info("Secrets loaded from environment", count=count)
        return count


class AWSSecretsLoader:
    """Load secrets from AWS Secrets Manager."""
    
    def __init__(self, region: str = "us-east-1"):
        """Initialize AWS secrets loader.
        
        Args:
            region: AWS region
        """
        self.region = region
        self._client = None
    
    def _get_client(self):
        """Get AWS Secrets Manager client."""
        if self._client is None:
            import boto3
            self._client = boto3.client(
                service_name="secretsmanager",
                region_name=self.region,
            )
        return self._client
    
    def load_secret(
        self,
        secrets_manager: SecretsManager,
        secret_name: str,
        target_name: str | None = None,
    ) -> bool:
        """Load secret from AWS.
        
        Args:
            secrets_manager: Secrets manager instance
            secret_name: AWS secret name
            target_name: Local name (defaults to secret_name)
            
        Returns:
            True if loaded successfully
        """
        try:
            client = self._get_client()
            response = client.get_secret_value(SecretId=secret_name)
            
            secret_value = response.get("SecretString")
            if secret_value:
                target = target_name or secret_name
                secrets_manager.set_secret(target, secret_value)
                logger.info("Secret loaded from AWS", name=secret_name)
                return True
            
            return False
        
        except Exception as e:
            logger.error(
                "Failed to load secret from AWS",
                name=secret_name,
                error=str(e),
            )
            return False


class AzureKeyVaultLoader:
    """Load secrets from Azure Key Vault."""
    
    def __init__(self, vault_url: str):
        """Initialize Azure Key Vault loader.
        
        Args:
            vault_url: Key Vault URL
        """
        self.vault_url = vault_url
        self._client = None
    
    def _get_client(self):
        """Get Azure Key Vault client."""
        if self._client is None:
            from azure.identity import DefaultAzureCredential
            from azure.keyvault.secrets import SecretClient
            
            credential = DefaultAzureCredential()
            self._client = SecretClient(
                vault_url=self.vault_url,
                credential=credential,
            )
        return self._client
    
    def load_secret(
        self,
        secrets_manager: SecretsManager,
        secret_name: str,
        target_name: str | None = None,
    ) -> bool:
        """Load secret from Azure.
        
        Args:
            secrets_manager: Secrets manager instance
            secret_name: Azure secret name
            target_name: Local name (defaults to secret_name)
            
        Returns:
            True if loaded successfully
        """
        try:
            client = self._get_client()
            secret = client.get_secret(secret_name)
            
            if secret.value:
                target = target_name or secret_name
                secrets_manager.set_secret(target, secret.value)
                logger.info("Secret loaded from Azure", name=secret_name)
                return True
            
            return False
        
        except Exception as e:
            logger.error(
                "Failed to load secret from Azure",
                name=secret_name,
                error=str(e),
            )
            return False


# Global secrets manager instance
_secrets_manager: SecretsManager | None = None


def init_secrets_manager(master_key: str | None = None) -> SecretsManager:
    """Initialize global secrets manager.
    
    Args:
        master_key: Master encryption key
        
    Returns:
        Secrets manager instance
    """
    global _secrets_manager
    _secrets_manager = SecretsManager(master_key)
    
    # Load from environment
    EnvironmentSecretsLoader.load(_secrets_manager)
    
    return _secrets_manager


def get_secrets_manager() -> SecretsManager | None:
    """Get global secrets manager instance.
    
    Returns:
        Secrets manager or None
    """
    return _secrets_manager


def get_secret(name: str, default: str | None = None) -> str | None:
    """Get secret from global manager.
    
    Args:
        name: Secret name
        default: Default value
        
    Returns:
        Secret value or default
    """
    manager = get_secrets_manager()
    if manager:
        return manager.get_secret(name, default)
    return default
