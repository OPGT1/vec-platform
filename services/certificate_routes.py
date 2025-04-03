# services/certificate_service.py

from utils import get_db_connection, supabase
from decimal import Decimal

class CertificateService:
    """Service class for certificate-related operations."""
    
    @staticmethod
    def create_burn_certificate(user_id, amount, recipient_name, recipient_email, certificate_hash=None):
        """
        Create a new burn certificate and process the transaction.
        
        Args:
            user_id: ID of the user burning credits
            amount: Amount of credits to burn
            recipient_name: Name of the certificate recipient
            recipient_email: Email of the certificate recipient
            certificate_hash: Optional hash for certificate verification
            
        Returns:
            dict: Certificate data including ID and environmental impact
        """
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            # Check user balance
            cursor.execute("""
                SELECT 
                    COALESCE((SELECT SUM(amount) FROM transactions WHERE receiver_id = %s), 0) -
                    COALESCE((SELECT SUM(amount) FROM transactions WHERE sender_id = %s), 0) AS balance
            """, (user_id, user_id))
            balance = cursor.fetchone()[0]
            
            if balance < amount:
                raise ValueError("Insufficient balance")
            
            # Create burn certificate
            cursor.execute("""
                INSERT INTO burn_certificates 
                (user_id, amount, recipient_name, recipient_email, certificate_hash)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
            """, (user_id, amount, recipient_name, recipient_email, certificate_hash))
            
            certificate_id = cursor.fetchone()[0]
            
            # Record transaction (to burn account)
            BURN_ACCOUNT_ID = 4  # ID of the burn account
            cursor.execute("""
                INSERT INTO transactions 
                (sender_id, receiver_id, amount, transaction_type)
                VALUES (%s, %s, %s, 'burn')
            """, (user_id, BURN_ACCOUNT_ID, amount))
            
            conn.commit()
            
            # Calculate environmental impact
            kwh_equivalent = float(amount) * 10
            co2_avoided = kwh_equivalent * 0.7
            
            return {
                "certificate_id": certificate_id,
                "amount": float(amount),
                "recipient_name": recipient_name,
                "recipient_email": recipient_email,
                "environmental_impact": {
                    "kwh_equivalent": kwh_equivalent,
                    "co2_avoided_kg": co2_avoided
                }
            }
            
        except Exception as e:
            conn.rollback()
            raise e
        
        finally:
            cursor.close()
            conn.close()
    
    @staticmethod
    def get_certificate(certificate_id, user_id=None):
        """
        Get certificate details by ID.
        If user_id is provided, only return the certificate if it belongs to that user.
        
        Args:
            certificate_id: ID of the certificate to retrieve
            user_id: Optional user ID to verify ownership
            
        Returns:
            dict: Certificate data including environmental impact
        """
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            query = """
                SELECT 
                    bc.id, bc.amount, bc.recipient_name, bc.recipient_email, 
                    bc.burn_date, bc.certificate_hash, bc.user_id,
                    u.email as burner_email
                FROM burn_certificates bc
                JOIN users u ON bc.user_id = u.id
                WHERE bc.id = %s
            """
            
            params = [certificate_id]
            
            if user_id:
                query += " AND bc.user_id = %s"
                params.append(user_id)
                
            cursor.execute(query, params)
            cert = cursor.fetchone()
            
            if not cert:
                return None
            
            # Calculate environmental impact
            kwh_equivalent = float(cert["amount"]) * 10
            co2_avoided = kwh_equivalent * 0.7
            
            return {
                "id": cert["id"],
                "amount": float(cert["amount"]),
                "recipient_name": cert["recipient_name"],
                "recipient_email": cert["recipient_email"],
                "burn_date": cert["burn_date"].isoformat(),
                "burner_email": cert["burner_email"],
                "user_id": cert["user_id"],
                "environmental_impact": {
                    "kwh_equivalent": kwh_equivalent,
                    "co2_avoided_kg": co2_avoided
                }
            }
            
        except Exception as e:
            raise e
        
        finally:
            cursor.close()
            conn.close()
    
    @staticmethod
    def get_user_certificates(user_id):
        """
        Get all certificates for a specific user.
        
        Args:
            user_id: ID of the user
            
        Returns:
            list: List of certificate data
        """
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                SELECT bc.*, u.email as burner_email
                FROM burn_certificates bc
                JOIN users u ON bc.user_id = u.id
                WHERE bc.user_id = %s
                ORDER BY bc.burn_date DESC
            """, (user_id,))
            
            certificates = cursor.fetchall()
            
            result = []
            for cert in certificates:
                kwh_equivalent = float(cert["amount"]) * 10
                co2_avoided = kwh_equivalent * 0.7
                
                result.append({
                    "id": cert["id"],
                    "amount": float(cert["amount"]),
                    "recipient_name": cert["recipient_name"],
                    "recipient_email": cert["recipient_email"],
                    "burn_date": cert["burn_date"].isoformat(),
                    "environmental_impact": {
                        "kwh_equivalent": kwh_equivalent,
                        "co2_avoided_kg": co2_avoided
                    }
                })
                
            return result
            
        except Exception as e:
            raise e
        
        finally:
            cursor.close()
            conn.close()