import { defineConfig } from "drizzle-kit";

const databaseUrl = process.env.IWO3_DATABASE_URL;
if (!databaseUrl) {
  throw new Error(
    "IWO3_DATABASE_URL env var is required. See infra/local/.env.example."
  );
}

export default defineConfig({
  schema: "./db/schema/*.ts",
  out: "./db/migrations",
  dialect: "postgresql",
  dbCredentials: { url: databaseUrl },
  strict: true,
  verbose: true,
});
