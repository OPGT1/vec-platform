# models.py

from pydantic import BaseModel, Field, EmailStr, validator
from typing import Optional, List, Dict, Union, Any
from datetime import datetime
from decimal import Decimal

# Base models with validation
class UserCreate(BaseModel):
    """Schema for creating a new user."""
    email: EmailStr
    password: str
    first_name: str
    last_name: str
    
    @validator('password')
    def password_strength(cls, v):
        """Check password strength."""
        if len(v) < 8:
            raise ValueError('Password must be at least 8 characters')
        return v

class BurnCertificateCreate(BaseModel):
    """Schema for creating a burn certificate."""
    amount: float = Field(..., gt=0)
    recipient_name: str = Field(..., min_length=1)
    recipient_email: EmailStr
    certificate_hash: Optional[str] = None
    
    @validator('amount')
    def validate_amount(cls, v):
        """Validate amount is positive."""
        if v <= 0:
            raise ValueError('Amount must be greater than zero')
        return v

class OrderCreate(BaseModel):
    """Schema for creating a new order."""
    order_type: str = Field(..., regex='^(buy|sell)$')
    price: float = Field(..., gt=0)
    amount: float = Field(..., gt=0)
    
    @validator('order_type')
    def validate_order_type(cls, v):
        """Validate order type."""
        if v not in ('buy', 'sell'):
            raise ValueError('Order type must be "buy" or "sell"')
        return v

# Response models
class UserResponse(BaseModel):
    """Schema for user response."""
    id: int
    email: str
    first_name: str
    last_name: str
    balance: float
    is_admin: bool

class TransactionResponse(BaseModel):
    """Schema for transaction response."""
    id: int
    sender: str
    receiver: str
    amount: float
    transaction_type: str
    transaction_date: datetime

class CertificateResponse(BaseModel):
    """Schema for certificate response."""
    id: int
    amount: float
    recipient_name: str
    recipient_email: str
    burn_date: datetime
    burner_email: str
    environmental_impact: Dict[str, float]

class OrderResponse(BaseModel):
    """Schema for order response."""
    id: int
    order_type: str
    price: float
    amount: float
    status: str
    created_at: datetime