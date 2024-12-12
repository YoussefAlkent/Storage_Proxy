#!/bin/bash
# Wait for MySQL to be ready
until mysql -h database -u root -proot -e "SELECT 1" > /dev/null 2>&1; do
  echo "Waiting for MySQL to be ready..."
  sleep 3
done

# Run the SQL initialization script
echo "MySQL is ready. Running the schema initialization..."
mysql -h database -u root -proot cloud_project < /docker-entrypoint-initdb.d/init_schema.sql
