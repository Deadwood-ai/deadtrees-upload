"""Authentication module for Supabase login."""

from typing import Optional, Tuple
from dataclasses import dataclass
import time
import httpx
from rich.console import Console

console = Console()


class AuthError(Exception):
	"""Authentication error."""
	pass


@dataclass
class AuthSession:
	"""Authentication session with token refresh support."""
	access_token: str
	refresh_token: str
	user_id: str
	expires_at: float  # Unix timestamp
	supabase_url: str
	supabase_key: str
	
	def is_expired(self, buffer_seconds: int = 300) -> bool:
		"""Check if token is expired or will expire soon."""
		return time.time() >= (self.expires_at - buffer_seconds)
	
	def refresh(self) -> None:
		"""Refresh the access token using refresh token."""
		refresh_url = f"{self.supabase_url.rstrip('/')}/auth/v1/token?grant_type=refresh_token"
		
		try:
			with httpx.Client(timeout=30.0) as client:
				response = client.post(
					refresh_url,
					json={"refresh_token": self.refresh_token},
					headers={
						"apikey": self.supabase_key,
						"Content-Type": "application/json",
					},
				)
				
				if response.status_code >= 400:
					raise AuthError("Failed to refresh token - please re-authenticate")
				
				data = response.json()
				self.access_token = data.get("access_token", self.access_token)
				self.refresh_token = data.get("refresh_token", self.refresh_token)
				
				# Supabase tokens typically expire in 3600 seconds (1 hour)
				expires_in = data.get("expires_in", 3600)
				self.expires_at = time.time() + expires_in
				
		except httpx.ConnectError:
			raise AuthError(f"Could not connect to Supabase for token refresh")
		except Exception as e:
			if isinstance(e, AuthError):
				raise
			raise AuthError(f"Token refresh failed: {str(e)}")
	
	def get_valid_token(self) -> str:
		"""Get a valid access token, refreshing if necessary."""
		if self.is_expired():
			self.refresh()
		return self.access_token


def login(email: str, password: str, api_url: str) -> Tuple[str, str]:
	"""
	Authenticate with Supabase and return access token and user ID.
	
	Args:
		email: User email
		password: User password
		api_url: Base API URL (used to derive Supabase URL)
	
	Returns:
		Tuple of (access_token, user_id)
	
	Raises:
		AuthError: If authentication fails
	"""
	# Derive Supabase URL from API URL
	# Production: https://data2.deadtrees.earth/api/v1/ -> need actual Supabase URL
	# For now, we'll use the API's auth endpoint
	
	auth_url = api_url.rstrip("/") + "/auth/login"
	
	try:
		with httpx.Client(timeout=30.0) as client:
			response = client.post(
				auth_url,
				json={"email": email, "password": password},
			)
			
			if response.status_code == 401:
				raise AuthError("Invalid email or password")
			
			response.raise_for_status()
			data = response.json()
			
			access_token = data.get("access_token")
			user_id = data.get("user", {}).get("id")
			
			if not access_token:
				raise AuthError("No access token in response")
			
			return access_token, user_id
			
	except httpx.ConnectError:
		raise AuthError(f"Could not connect to {auth_url}")
	except httpx.HTTPStatusError as e:
		raise AuthError(f"Authentication failed: {e.response.text}")
	except Exception as e:
		raise AuthError(f"Authentication error: {str(e)}")


def login_with_supabase(email: str, password: str, supabase_url: str, supabase_key: str) -> Tuple[str, str]:
	"""
	Authenticate directly with Supabase (simple version).
	
	Args:
		email: User email
		password: User password
		supabase_url: Supabase project URL
		supabase_key: Supabase anon key
	
	Returns:
		Tuple of (access_token, user_id)
	
	Raises:
		AuthError: If authentication fails
	"""
	session = create_auth_session(email, password, supabase_url, supabase_key)
	return session.access_token, session.user_id


def create_auth_session(email: str, password: str, supabase_url: str, supabase_key: str) -> AuthSession:
	"""
	Authenticate with Supabase and create a session with refresh token support.
	
	Args:
		email: User email
		password: User password
		supabase_url: Supabase project URL
		supabase_key: Supabase anon key
	
	Returns:
		AuthSession with token refresh support
	
	Raises:
		AuthError: If authentication fails
	"""
	auth_url = f"{supabase_url.rstrip('/')}/auth/v1/token?grant_type=password"
	
	try:
		with httpx.Client(timeout=30.0) as client:
			response = client.post(
				auth_url,
				json={"email": email, "password": password},
				headers={
					"apikey": supabase_key,
					"Content-Type": "application/json",
				},
			)
			
			if response.status_code == 400:
				error_data = response.json()
				error_msg = error_data.get("error_description", error_data.get("msg", "Invalid credentials"))
				raise AuthError(error_msg)
			
			response.raise_for_status()
			data = response.json()
			
			access_token = data.get("access_token")
			refresh_token = data.get("refresh_token", "")
			user_id = data.get("user", {}).get("id")
			expires_in = data.get("expires_in", 3600)  # Default 1 hour
			
			if not access_token:
				raise AuthError("No access token in response")
			
			return AuthSession(
				access_token=access_token,
				refresh_token=refresh_token,
				user_id=user_id,
				expires_at=time.time() + expires_in,
				supabase_url=supabase_url,
				supabase_key=supabase_key,
			)
			
	except httpx.ConnectError:
		raise AuthError(f"Could not connect to Supabase at {supabase_url}")
	except httpx.HTTPStatusError as e:
		raise AuthError(f"Authentication failed: {e.response.text}")
	except AuthError:
		raise
	except Exception as e:
		raise AuthError(f"Authentication error: {str(e)}")


def verify_token(token: str, api_url: str) -> bool:
	"""
	Verify that a token is still valid.
	
	Args:
		token: Access token to verify
		api_url: Base API URL
	
	Returns:
		True if token is valid
	"""
	verify_url = api_url.rstrip("/") + "/auth/verify"
	
	try:
		with httpx.Client(timeout=10.0) as client:
			response = client.get(
				verify_url,
				headers={"Authorization": f"Bearer {token}"},
			)
			return response.status_code == 200
	except Exception:
		return False
