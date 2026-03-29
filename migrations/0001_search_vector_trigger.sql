-- Loop 23 (Phase 2): Full-text search vector + GIN index for Know-How keyword retrieval
-- This trigger auto-populates search_vector from name + extracted_text + tags on INSERT/UPDATE.
-- The GIN index enables fast plainto_tsquery lookups, replacing the old ILIKE content scan.

ALTER TABLE artifacts ADD COLUMN IF NOT EXISTS search_vector tsvector;

CREATE OR REPLACE FUNCTION artifacts_search_vector_update() RETURNS trigger AS $$
BEGIN
  NEW.search_vector := to_tsvector('english',
    COALESCE(NEW.name, '') || ' ' ||
    COALESCE(NEW.extracted_text, '') || ' ' ||
    COALESCE(array_to_string(NEW.tags, ' '), ''));
  RETURN NEW;
END $$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS artifacts_search_vector_trigger ON artifacts;
CREATE TRIGGER artifacts_search_vector_trigger
  BEFORE INSERT OR UPDATE ON artifacts
  FOR EACH ROW EXECUTE FUNCTION artifacts_search_vector_update();

CREATE INDEX IF NOT EXISTS idx_artifacts_search_vector ON artifacts USING GIN(search_vector);
