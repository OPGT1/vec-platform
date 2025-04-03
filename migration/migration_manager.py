# migrations/migration_manager.py

import os
import glob
import re
import psycopg2
from utils import get_db_connection

class MigrationManager:
    """
    Manages database migrations to track and apply schema changes.
    """
    
    def __init__(self, migrations_dir='migrations'):
        self.migrations_dir = migrations_dir
        # Ensure migrations directory exists
        os.makedirs(migrations_dir, exist_ok=True)
        
        # Create migrations table if it doesn't exist
        self._ensure_migrations_table()
    
    def _ensure_migrations_table(self):
        """
        Create the migrations table if it doesn't exist.
        This table tracks which migrations have been applied.
        """
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS migrations (
                id SERIAL PRIMARY KEY,
                migration_name VARCHAR(255) UNIQUE NOT NULL,
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        
        conn.commit()
        cursor.close()
        conn.close()
    
    def get_applied_migrations(self):
        """
        Get a list of migrations that have already been applied.
        """
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT migration_name FROM migrations ORDER BY id")
        applied = [row[0] for row in cursor.fetchall()]
        
        cursor.close()
        conn.close()
        
        return applied
    
    def get_available_migrations(self):
        """
        Get a list of available migration files.
        """
        pattern = os.path.join(self.migrations_dir, '*.sql')
        return sorted([os.path.basename(f) for f in glob.glob(pattern)])
    
    def get_pending_migrations(self):
        """
        Get a list of migrations that need to be applied.
        """
        applied = self.get_applied_migrations()
        available = self.get_available_migrations()
        return [m for m in available if m not in applied]
    
    def apply_migration(self, migration_name):
        """
        Apply a single migration.
        """
        migration_path = os.path.join(self.migrations_dir, migration_name)
        
        if not os.path.exists(migration_path):
            raise FileNotFoundError(f"Migration file not found: {migration_path}")
        
        # Read the migration file
        with open(migration_path, 'r') as f:
            sql = f.read()
        
        # Apply the migration
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            # Execute the migration
            cursor.execute(sql)
            
            # Record that this migration has been applied
            cursor.execute(
                "INSERT INTO migrations (migration_name) VALUES (%s)",
                (migration_name,)
            )
            
            conn.commit()
            print(f"Applied migration: {migration_name}")
        
        except Exception as e:
            conn.rollback()
            print(f"Error applying migration {migration_name}: {e}")
            raise e
        
        finally:
            cursor.close()
            conn.close()
    
    def apply_pending_migrations(self):
        """
        Apply all pending migrations.
        """
        pending = self.get_pending_migrations()
        
        if not pending:
            print("No pending migrations.")
            return
        
        print(f"Applying {len(pending)} migrations...")
        
        for migration in pending:
            self.apply_migration(migration)
        
        print("Migrations complete.")
    
    def create_migration(self, name):
        """
        Create a new migration file.
        """
        # Sanitize the name
        name = re.sub(r'[^a-zA-Z0-9_]', '_', name)
        
        # Get timestamp for ordering
        from datetime import datetime
        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        
        # Create filename
        filename = f"{timestamp}_{name}.sql"
        filepath = os.path.join(self.migrations_dir, filename)
        
        # Create the file with a template
        with open(filepath, 'w') as f:
            f.write(f"-- Migration: {name}\n")
            f.write(f"-- Created at: {datetime.now().isoformat()}\n\n")
            f.write("-- Write your SQL here\n\n")
            f.write("-- Example:\n")
            f.write("-- ALTER TABLE users ADD COLUMN new_field VARCHAR(255);\n")
        
        print(f"Created migration file: {filepath}")
        return filepath

# Example migrations:

# migrations/20250401120000_add_user_verified_field.sql
"""
-- Migration: add_user_verified_field
-- Created at: 2025-04-01T12:00:00

-- Add verified field to users
ALTER TABLE users ADD COLUMN verified BOOLEAN DEFAULT FALSE;

-- Add index on verified field
CREATE INDEX idx_users_verified ON users(verified);
"""

# migrations/20250401120100_add_notification_table.sql
"""
-- Migration: add_notification_table
-- Created at: 2025-04-01T12:01:00

-- Create notifications table
CREATE TABLE notifications (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    message TEXT NOT NULL,
    is_read BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Add index for fast lookup by user
CREATE INDEX idx_notifications_user_id ON notifications(user_id);
"""