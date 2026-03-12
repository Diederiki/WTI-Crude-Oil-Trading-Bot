"""Security middleware for FastAPI.

Provides security headers, input validation, and request sanitization
to protect against common web vulnerabilities.
"""

import re
from typing import Any, Callable

from fastapi import Request, Response
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from src.core.logging_config import get_logger

logger = get_logger("security")


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all responses."""
    
    def __init__(
        self,
        app,
        content_security_policy: str | None = None,
        allow_iframe: bool = False,
    ):
        """Initialize middleware.
        
        Args:
            app: FastAPI application
            content_security_policy: Custom CSP header
            allow_iframe: Whether to allow iframe embedding
        """
        super().__init__(app)
        self.content_security_policy = content_security_policy or (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: https:; "
            "font-src 'self'; "
            "connect-src 'self' ws: wss:;"
        )
        self.allow_iframe = allow_iframe
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Add security headers to response.
        
        Args:
            request: Incoming request
            call_next: Next middleware/handler
            
        Returns:
            Response with security headers
        """
        response = await call_next(request)
        
        # Prevent MIME type sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"
        
        # Prevent clickjacking
        if not self.allow_iframe:
            response.headers["X-Frame-Options"] = "DENY"
        
        # Enable XSS protection
        response.headers["X-XSS-Protection"] = "1; mode=block"
        
        # Content Security Policy
        response.headers["Content-Security-Policy"] = self.content_security_policy
        
        # Referrer Policy
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        
        # Permissions Policy
        response.headers["Permissions-Policy"] = (
            "accelerometer=(), "
            "camera=(), "
            "geolocation=(), "
            "gyroscope=(), "
            "magnetometer=(), "
            "microphone=(), "
            "payment=(), "
            "usb=()"
        )
        
        # Strict Transport Security (HTTPS only)
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains; preload"
        )
        
        return response


class InputValidationMiddleware(BaseHTTPMiddleware):
    """Validate and sanitize incoming requests."""
    
    # Patterns for common attacks
    SQL_INJECTION_PATTERNS = [
        r"(\%27)|(\')|(\-\-)|(\%23)|(#)",
        r"((\%3D)|(=))[^\n]*((\%27)|(\')|(\-\-)|(\%3B)|(;))",
        r"\w*((\%27)|(\'))((\%6F)|o|(\%4F))((\%72)|r|(\%52))",
        r"((\%27)|(\'))union",
        r"exec(\s|\+)+(s|x)p\w+",
        r"UNION\s+SELECT",
        r"INSERT\s+INTO",
        r"DELETE\s+FROM",
        r"DROP\s+TABLE",
    ]
    
    XSS_PATTERNS = [
        r"<script[^>]*>[\s\S]*?</script>",
        r"javascript:",
        r"on\w+\s*=",
        r"<iframe",
        r"<object",
        r"<embed",
    ]
    
    PATH_TRAVERSAL_PATTERN = r"\.\./|\.\.\\|%2e%2e%2f|%2e%2e/|%2e\.\./|%252e%252e%252f"
    
    MAX_BODY_SIZE = 10 * 1024 * 1024  # 10MB
    MAX_HEADER_SIZE = 16 * 1024  # 16KB
    MAX_QUERY_STRING = 4096  # 4KB
    
    def __init__(self, app, block_on_violation: bool = True):
        """Initialize middleware.
        
        Args:
            app: FastAPI application
            block_on_violation: Whether to block requests with violations
        """
        super().__init__(app)
        self.block_on_violation = block_on_violation
        self._compile_patterns()
    
    def _compile_patterns(self) -> None:
        """Compile regex patterns."""
        self.sql_patterns = [re.compile(p, re.IGNORECASE) for p in self.SQL_INJECTION_PATTERNS]
        self.xss_patterns = [re.compile(p, re.IGNORECASE) for p in self.XSS_PATTERNS]
        self.path_pattern = re.compile(self.PATH_TRAVERSAL_PATTERN, re.IGNORECASE)
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Validate incoming request.
        
        Args:
            request: Incoming request
            call_next: Next middleware/handler
            
        Returns:
            Response or error
        """
        violations = []
        
        # Check request size
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > self.MAX_BODY_SIZE:
            violations.append(f"Body size exceeds {self.MAX_BODY_SIZE} bytes")
        
        # Check header size
        header_size = sum(len(k) + len(v) for k, v in request.headers.items())
        if header_size > self.MAX_HEADER_SIZE:
            violations.append(f"Header size exceeds {self.MAX_HEADER_SIZE} bytes")
        
        # Check query string
        query_string = str(request.query_params)
        if len(query_string) > self.MAX_QUERY_STRING:
            violations.append(f"Query string exceeds {self.MAX_QUERY_STRING} bytes")
        
        # Check path for traversal
        path = request.url.path
        if self.path_pattern.search(path):
            violations.append("Path traversal attempt detected")
        
        # Check query parameters
        for key, value in request.query_params.items():
            if self._check_injection(value):
                violations.append(f"Suspicious content in query parameter: {key}")
        
        # Check headers
        for key, value in request.headers.items():
            if key.lower() in ["user-agent", "referer", "x-forwarded-for"]:
                if self._check_injection(value):
                    violations.append(f"Suspicious content in header: {key}")
        
        # Log violations
        if violations:
            logger.warning(
                "Security violations detected",
                path=path,
                violations=violations,
                client_ip=request.client.host if request.client else None,
            )
            
            if self.block_on_violation:
                from fastapi.responses import JSONResponse
                return JSONResponse(
                    status_code=400,
                    content={
                        "error": "Bad Request",
                        "message": "Request contains invalid content",
                    },
                )
        
        return await call_next(request)
    
    def _check_injection(self, value: str) -> bool:
        """Check string for injection patterns.
        
        Args:
            value: String to check
            
        Returns:
            True if injection detected
        """
        for pattern in self.sql_patterns:
            if pattern.search(value):
                return True
        
        for pattern in self.xss_patterns:
            if pattern.search(value):
                return True
        
        return False


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Rate limiting middleware."""
    
    def __init__(
        self,
        app,
        requests_per_minute: int = 100,
        burst_size: int = 20,
        use_distributed: bool = False,
    ):
        """Initialize middleware.
        
        Args:
            app: FastAPI application
            requests_per_minute: Rate limit
            burst_size: Burst allowance
            use_distributed: Use Redis-based distributed limiter
        """
        super().__init__(app)
        self.requests_per_minute = requests_per_minute
        self.burst_size = burst_size
        self.use_distributed = use_distributed
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Apply rate limiting.
        
        Args:
            request: Incoming request
            call_next: Next middleware/handler
            
        Returns:
            Response or rate limit error
        """
        from src.core.rate_limiter import (
            DistributedRateLimiter,
            RateLimitConfig,
            RateLimiter,
        )
        
        # Get client identifier
        client_id = self._get_client_id(request)
        
        # Check rate limit
        config = RateLimitConfig(
            requests_per_second=self.requests_per_minute / 60,
            burst_size=self.burst_size,
            window_seconds=60,
        )
        
        if self.use_distributed:
            limiter = DistributedRateLimiter()
        else:
            limiter = RateLimiter()
        
        allowed, metadata = await limiter.check_rate_limit(client_id, config)
        
        if not allowed:
            from fastapi.responses import JSONResponse
            
            retry_after = int(metadata.get("retry_after", 60))
            
            logger.warning(
                "Rate limit exceeded",
                client_id=client_id,
                path=request.url.path,
            )
            
            response = JSONResponse(
                status_code=429,
                content={
                    "error": "Too Many Requests",
                    "message": "Rate limit exceeded",
                    "retry_after": retry_after,
                },
            )
            response.headers["Retry-After"] = str(retry_after)
            response.headers["X-RateLimit-Limit"] = str(self.requests_per_minute)
            response.headers["X-RateLimit-Remaining"] = "0"
            
            return response
        
        # Add rate limit headers
        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(self.requests_per_minute)
        response.headers["X-RateLimit-Remaining"] = str(
            metadata.get("window_remaining", 0)
        )
        
        return response
    
    def _get_client_id(self, request: Request) -> str:
        """Get client identifier from request.
        
        Args:
            request: Incoming request
            
        Returns:
            Client identifier
        """
        # Try API key first
        api_key = request.query_params.get("api_key")
        if api_key:
            return f"api:{api_key[:8]}"
        
        # Try authenticated user
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            return f"token:{token[:8]}"
        
        # Fall back to IP address
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return f"ip:{forwarded.split(',')[0].strip()}"
        
        if request.client:
            return f"ip:{request.client.host}"
        
        return "ip:unknown"


def sanitize_string(value: str, max_length: int = 1000) -> str:
    """Sanitize a string value.
    
    Args:
        value: String to sanitize
        max_length: Maximum allowed length
        
    Returns:
        Sanitized string
    """
    if not isinstance(value, str):
        return ""
    
    # Truncate if too long
    if len(value) > max_length:
        value = value[:max_length]
    
    # Remove null bytes
    value = value.replace("\x00", "")
    
    # Remove control characters except newlines and tabs
    value = "".join(
        char for char in value
        if char == "\n" or char == "\t" or ord(char) >= 32
    )
    
    return value.strip()


def sanitize_log_message(message: str) -> str:
    """Sanitize message for safe logging.
    
    Masks potential sensitive data like API keys, passwords, tokens.
    
    Args:
        message: Message to sanitize
        
    Returns:
        Sanitized message
    """
    import re
    
    # Mask API keys
    message = re.sub(
        r'(api[_-]?key["\']?\s*[:=]\s*["\']?)[\w-]+',
        r'\1***MASKED***',
        message,
        flags=re.IGNORECASE,
    )
    
    # Mask passwords
    message = re.sub(
        r'(password["\']?\s*[:=]\s*["\']?)[^\s"\']+',
        r'\1***MASKED***',
        message,
        flags=re.IGNORECASE,
    )
    
    # Mask tokens
    message = re.sub(
        r'(token["\']?\s*[:=]\s*["\']?)[\w-]+',
        r'\1***MASKED***',
        message,
        flags=re.IGNORECASE,
    )
    
    # Mask bearer tokens in auth headers
    message = re.sub(
        r'(Bearer\s+)\S+',
        r'\1***MASKED***',
        message,
        flags=re.IGNORECASE,
    )
    
    return message
