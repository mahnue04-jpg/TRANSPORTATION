/**
 * Amicor Nova — Database setup script
 * Connects to PostgreSQL using DATABASE_URL and applies database.sql
 *
 * Usage: npm run setup
 */

const fs = require('fs');
const path = require('path');
const { Client } = require('pg');
require('dotenv').config({ path: path.join(__dirname, '..', '.env') });

const DATABASE_URL = process.env.DATABASE_URL;

if (!DATABASE_URL) {
  console.error('ERROR: DATABASE_URL is not set in .env');
  process.exit(1);
}

async function setup() {
  const sqlPath = path.join(__dirname, '..', 'database.sql');

  if (!fs.existsSync(sqlPath)) {
    console.error(`ERROR: Schema file not found at ${sqlPath}`);
    process.exit(1);
  }

  const schema = fs.readFileSync(sqlPath, 'utf8');
  const client = new Client({ connectionString: DATABASE_URL });

  try {
    console.log('Connecting to PostgreSQL...');
    await client.connect();
    console.log('Connected. Applying schema...');

    await client.query(schema);

    console.log('Schema applied successfully.');
    console.log('Tables: users, facilities, drivers, patients, trips, payments, alerts, audit_log');
  } catch (err) {
    console.error('Setup failed:', err.message);
    if (err.code === 'ECONNREFUSED') {
      console.error('Hint: Ensure PostgreSQL is running and DATABASE_URL is correct.');
    }
    process.exit(1);
  } finally {
    await client.end();
  }
}

setup();
