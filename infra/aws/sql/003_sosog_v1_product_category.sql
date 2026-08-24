-- Align the live V1 constraint with promotion_engine.taxonomy's DROP bucket.
ALTER TABLE sosog_v1.classifications
    DROP CONSTRAINT IF EXISTS classifications_product_category_check;

ALTER TABLE sosog_v1.classifications
    ADD CONSTRAINT classifications_product_category_check CHECK (
        product_category IN (
            'FULLY_CRYSTALLIZABLE', 'DECOMPOSABLE',
            'FULLY_AGENTIC', 'FULLY_MANUAL', 'INSUFFICIENT_EVIDENCE'
        )
    );
