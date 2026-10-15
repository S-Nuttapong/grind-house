-- migrate:up

UPDATE searches
SET keywords = keywords || ARRAY['Product Engineer']
WHERE name = 'Software roles'
  AND NOT ('Product Engineer' = ANY (keywords));

UPDATE searches
SET keywords = keywords || ARRAY['Growth Engineer']
WHERE name = 'Software roles'
  AND NOT ('Growth Engineer' = ANY (keywords));

UPDATE searches
SET keywords = keywords || ARRAY['Web Engineer']
WHERE name = 'Software roles'
  AND NOT ('Web Engineer' = ANY (keywords));

-- migrate:down

UPDATE searches
SET keywords = array_remove(keywords, 'Product Engineer')
WHERE name = 'Software roles';

UPDATE searches
SET keywords = array_remove(keywords, 'Growth Engineer')
WHERE name = 'Software roles';

UPDATE searches
SET keywords = array_remove(keywords, 'Web Engineer')
WHERE name = 'Software roles';
