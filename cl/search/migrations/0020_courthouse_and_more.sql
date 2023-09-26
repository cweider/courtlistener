BEGIN;
--
-- Create model Courthouse
--
CREATE TABLE "search_courthouse" ("id" integer NOT NULL PRIMARY KEY GENERATED BY DEFAULT AS IDENTITY, "court_seat" boolean NULL, "building_name" text NOT NULL, "address1" text NOT NULL, "address2" text NOT NULL, "city" text NOT NULL, "county" text NOT NULL, "state" varchar(2) NOT NULL, "zip_code" varchar(10) NOT NULL, "country_code" text NOT NULL);
--
-- Remove trigger update_or_delete_snapshot_delete from model court
--
DROP TRIGGER IF EXISTS pgtrigger_update_or_delete_snapshot_delete_84ec4 ON "search_court";
--
-- Remove trigger update_or_delete_snapshot_update from model court
--
DROP TRIGGER IF EXISTS pgtrigger_update_or_delete_snapshot_update_c94ab ON "search_court";
--
-- Add field appeals_to to court
--
CREATE TABLE "search_court_appeals_to" ("id" integer NOT NULL PRIMARY KEY GENERATED BY DEFAULT AS IDENTITY, "from_court_id" varchar(15) NOT NULL, "to_court_id" varchar(15) NOT NULL);
--
-- Add field parent_court to court
--
ALTER TABLE "search_court" ADD COLUMN "parent_court_id" varchar(15) NULL CONSTRAINT "search_court_parent_court_id_51ba1d28_fk_search_court_id" REFERENCES "search_court"("id") DEFERRABLE INITIALLY DEFERRED; SET CONSTRAINTS "search_court_parent_court_id_51ba1d28_fk_search_court_id" IMMEDIATE;
--
-- Add field parent_court to courtevent
--
ALTER TABLE "search_courtevent" ADD COLUMN "parent_court_id" varchar(15) NULL;
--
-- Alter field jurisdiction on court
--
-- (no-op)
--
-- Alter field jurisdiction on courtevent
--
-- (no-op)
--
-- Create trigger update_or_delete_snapshot_update on model court
--

            CREATE OR REPLACE FUNCTION "public"._pgtrigger_should_ignore(
                trigger_name NAME
            )
            RETURNS BOOLEAN AS $$
                DECLARE
                    _pgtrigger_ignore TEXT[];
                    _result BOOLEAN;
                BEGIN
                    BEGIN
                        SELECT INTO _pgtrigger_ignore
                            CURRENT_SETTING('pgtrigger.ignore');
                        EXCEPTION WHEN OTHERS THEN
                    END;
                    IF _pgtrigger_ignore IS NOT NULL THEN
                        SELECT trigger_name = ANY(_pgtrigger_ignore)
                        INTO _result;
                        RETURN _result;
                    ELSE
                        RETURN FALSE;
                    END IF;
                END;
            $$ LANGUAGE plpgsql;

            CREATE OR REPLACE FUNCTION pgtrigger_update_or_delete_snapshot_update_c94ab()
            RETURNS TRIGGER AS $$

                BEGIN
                    IF ("public"._pgtrigger_should_ignore(TG_NAME) IS TRUE) THEN
                        IF (TG_OP = 'DELETE') THEN
                            RETURN OLD;
                        ELSE
                            RETURN NEW;
                        END IF;
                    END IF;
                    INSERT INTO "search_courtevent" ("citation_string", "date_last_pacer_contact", "date_modified", "end_date", "fjc_court_id", "full_name", "has_opinion_scraper", "has_oral_argument_scraper", "id", "in_use", "jurisdiction", "notes", "pacer_court_id", "pacer_has_rss_feed", "pacer_rss_entry_types", "parent_court_id", "pgh_context_id", "pgh_created_at", "pgh_label", "pgh_obj_id", "position", "short_name", "start_date", "url") VALUES (OLD."citation_string", OLD."date_last_pacer_contact", OLD."date_modified", OLD."end_date", OLD."fjc_court_id", OLD."full_name", OLD."has_opinion_scraper", OLD."has_oral_argument_scraper", OLD."id", OLD."in_use", OLD."jurisdiction", OLD."notes", OLD."pacer_court_id", OLD."pacer_has_rss_feed", OLD."pacer_rss_entry_types", OLD."parent_court_id", _pgh_attach_context(), NOW(), 'update_or_delete_snapshot', OLD."id", OLD."position", OLD."short_name", OLD."start_date", OLD."url"); RETURN NULL;
                END;
            $$ LANGUAGE plpgsql;

            DROP TRIGGER IF EXISTS pgtrigger_update_or_delete_snapshot_update_c94ab ON "search_court";
            CREATE  TRIGGER pgtrigger_update_or_delete_snapshot_update_c94ab
                AFTER UPDATE ON "search_court"


                FOR EACH ROW WHEN (OLD."id" IS DISTINCT FROM (NEW."id") OR OLD."parent_court_id" IS DISTINCT FROM (NEW."parent_court_id") OR OLD."pacer_court_id" IS DISTINCT FROM (NEW."pacer_court_id") OR OLD."pacer_has_rss_feed" IS DISTINCT FROM (NEW."pacer_has_rss_feed") OR OLD."pacer_rss_entry_types" IS DISTINCT FROM (NEW."pacer_rss_entry_types") OR OLD."date_last_pacer_contact" IS DISTINCT FROM (NEW."date_last_pacer_contact") OR OLD."fjc_court_id" IS DISTINCT FROM (NEW."fjc_court_id") OR OLD."in_use" IS DISTINCT FROM (NEW."in_use") OR OLD."has_opinion_scraper" IS DISTINCT FROM (NEW."has_opinion_scraper") OR OLD."has_oral_argument_scraper" IS DISTINCT FROM (NEW."has_oral_argument_scraper") OR OLD."position" IS DISTINCT FROM (NEW."position") OR OLD."citation_string" IS DISTINCT FROM (NEW."citation_string") OR OLD."short_name" IS DISTINCT FROM (NEW."short_name") OR OLD."full_name" IS DISTINCT FROM (NEW."full_name") OR OLD."url" IS DISTINCT FROM (NEW."url") OR OLD."start_date" IS DISTINCT FROM (NEW."start_date") OR OLD."end_date" IS DISTINCT FROM (NEW."end_date") OR OLD."jurisdiction" IS DISTINCT FROM (NEW."jurisdiction") OR OLD."notes" IS DISTINCT FROM (NEW."notes"))
                EXECUTE PROCEDURE pgtrigger_update_or_delete_snapshot_update_c94ab();

            COMMENT ON TRIGGER pgtrigger_update_or_delete_snapshot_update_c94ab ON "search_court" IS 'd886ec89d1364a03c4f04630b4a0e1363d97fcc1';

--
-- Create trigger update_or_delete_snapshot_delete on model court
--

            CREATE OR REPLACE FUNCTION "public"._pgtrigger_should_ignore(
                trigger_name NAME
            )
            RETURNS BOOLEAN AS $$
                DECLARE
                    _pgtrigger_ignore TEXT[];
                    _result BOOLEAN;
                BEGIN
                    BEGIN
                        SELECT INTO _pgtrigger_ignore
                            CURRENT_SETTING('pgtrigger.ignore');
                        EXCEPTION WHEN OTHERS THEN
                    END;
                    IF _pgtrigger_ignore IS NOT NULL THEN
                        SELECT trigger_name = ANY(_pgtrigger_ignore)
                        INTO _result;
                        RETURN _result;
                    ELSE
                        RETURN FALSE;
                    END IF;
                END;
            $$ LANGUAGE plpgsql;

            CREATE OR REPLACE FUNCTION pgtrigger_update_or_delete_snapshot_delete_84ec4()
            RETURNS TRIGGER AS $$

                BEGIN
                    IF ("public"._pgtrigger_should_ignore(TG_NAME) IS TRUE) THEN
                        IF (TG_OP = 'DELETE') THEN
                            RETURN OLD;
                        ELSE
                            RETURN NEW;
                        END IF;
                    END IF;
                    INSERT INTO "search_courtevent" ("citation_string", "date_last_pacer_contact", "date_modified", "end_date", "fjc_court_id", "full_name", "has_opinion_scraper", "has_oral_argument_scraper", "id", "in_use", "jurisdiction", "notes", "pacer_court_id", "pacer_has_rss_feed", "pacer_rss_entry_types", "parent_court_id", "pgh_context_id", "pgh_created_at", "pgh_label", "pgh_obj_id", "position", "short_name", "start_date", "url") VALUES (OLD."citation_string", OLD."date_last_pacer_contact", OLD."date_modified", OLD."end_date", OLD."fjc_court_id", OLD."full_name", OLD."has_opinion_scraper", OLD."has_oral_argument_scraper", OLD."id", OLD."in_use", OLD."jurisdiction", OLD."notes", OLD."pacer_court_id", OLD."pacer_has_rss_feed", OLD."pacer_rss_entry_types", OLD."parent_court_id", _pgh_attach_context(), NOW(), 'update_or_delete_snapshot', OLD."id", OLD."position", OLD."short_name", OLD."start_date", OLD."url"); RETURN NULL;
                END;
            $$ LANGUAGE plpgsql;

            DROP TRIGGER IF EXISTS pgtrigger_update_or_delete_snapshot_delete_84ec4 ON "search_court";
            CREATE  TRIGGER pgtrigger_update_or_delete_snapshot_delete_84ec4
                AFTER DELETE ON "search_court"


                FOR EACH ROW
                EXECUTE PROCEDURE pgtrigger_update_or_delete_snapshot_delete_84ec4();

            COMMENT ON TRIGGER pgtrigger_update_or_delete_snapshot_delete_84ec4 ON "search_court" IS 'd72fa3660f1c1d7de0feadd1ba92c2e70f48da07';

--
-- Add field court to courthouse
--
ALTER TABLE "search_courthouse" ADD COLUMN "court_id" varchar(15) NOT NULL CONSTRAINT "search_courthouse_court_id_6528f572_fk_search_court_id" REFERENCES "search_court"("id") DEFERRABLE INITIALLY DEFERRED; SET CONSTRAINTS "search_courthouse_court_id_6528f572_fk_search_court_id" IMMEDIATE;
ALTER TABLE "search_court_appeals_to" ADD CONSTRAINT "search_court_appeals_to_from_court_id_to_court_id_006ed7af_uniq" UNIQUE ("from_court_id", "to_court_id");
ALTER TABLE "search_court_appeals_to" ADD CONSTRAINT "search_court_appeals_from_court_id_fb09cc1a_fk_search_co" FOREIGN KEY ("from_court_id") REFERENCES "search_court" ("id") DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE "search_court_appeals_to" ADD CONSTRAINT "search_court_appeals_to_to_court_id_49ac3d9c_fk_search_court_id" FOREIGN KEY ("to_court_id") REFERENCES "search_court" ("id") DEFERRABLE INITIALLY DEFERRED;
CREATE INDEX "search_court_appeals_to_from_court_id_fb09cc1a" ON "search_court_appeals_to" ("from_court_id");
CREATE INDEX "search_court_appeals_to_from_court_id_fb09cc1a_like" ON "search_court_appeals_to" ("from_court_id" varchar_pattern_ops);
CREATE INDEX "search_court_appeals_to_to_court_id_49ac3d9c" ON "search_court_appeals_to" ("to_court_id");
CREATE INDEX "search_court_appeals_to_to_court_id_49ac3d9c_like" ON "search_court_appeals_to" ("to_court_id" varchar_pattern_ops);
CREATE INDEX "search_court_parent_court_id_51ba1d28" ON "search_court" ("parent_court_id");
CREATE INDEX "search_court_parent_court_id_51ba1d28_like" ON "search_court" ("parent_court_id" varchar_pattern_ops);
CREATE INDEX "search_courtevent_parent_court_id_342036cc" ON "search_courtevent" ("parent_court_id");
CREATE INDEX "search_courtevent_parent_court_id_342036cc_like" ON "search_courtevent" ("parent_court_id" varchar_pattern_ops);
CREATE INDEX "search_courthouse_court_id_6528f572" ON "search_courthouse" ("court_id");
CREATE INDEX "search_courthouse_court_id_6528f572_like" ON "search_courthouse" ("court_id" varchar_pattern_ops);
COMMIT;