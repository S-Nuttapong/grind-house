-- migrate:up

UPDATE scrape_settings
SET allowed_roles = allowed_roles || ARRAY[
  'product_engineer', 'growth_engineer', 'platform_engineer', 'web_engineer', 'forward_deployed'
]
WHERE NOT ('product_engineer' = ANY (allowed_roles));

UPDATE searches
SET keywords = keywords || ARRAY['Platform Engineer']
WHERE name = 'Software roles'
  AND NOT ('Platform Engineer' = ANY (keywords));

UPDATE searches
SET keywords = keywords || ARRAY['Web Engineer']
WHERE name = 'Software roles'
  AND NOT ('Web Engineer' = ANY (keywords));

-- Longer mixed titles first, so a later platform update does not overwrite them.
UPDATE jobs SET role = 'data'
WHERE title ~* '\mdata platform engineer\M';

UPDATE jobs SET role = 'mobile'
WHERE title ~* '\m(android|mobile) platform engineer\M';

UPDATE jobs SET role = 'security'
WHERE title ~* '\msecurity platform engineer\M';

UPDATE jobs SET role = 'ml'
WHERE title ~* '\m(ml|machine learning|ai) platform engineer\M';

UPDATE jobs SET role = 'platform_engineer'
WHERE title ~* '\mplatform engineer\M'
  AND title !~* '\m(data|android|mobile|security|ml|machine learning|ai) platform engineer\M';

UPDATE jobs SET role = 'product_engineer'
WHERE title ~* '\mproduct engineer\M';

UPDATE jobs SET role = 'growth_engineer'
WHERE title ~* '\mgrowth engineer\M';

UPDATE jobs SET role = 'forward_deployed'
WHERE title ~* '\mforward deployed\M';

-- Plain web titles only. A stack word in the title keeps its own role.
UPDATE jobs SET role = 'web_engineer'
WHERE title ~* '\mweb (engineer|developer)\M'
  AND title !~* '\m(full[\s-]?stack|front[\s-]?end|frontend|back[\s-]?end|backend|react)\M';

-- migrate:down

UPDATE jobs SET role = 'software'
WHERE role IN ('product_engineer', 'growth_engineer', 'web_engineer');

UPDATE jobs SET role = 'devops'
WHERE role = 'platform_engineer';

UPDATE jobs SET role = NULL
WHERE role = 'forward_deployed';

UPDATE searches
SET keywords = array_remove(keywords, 'Web Engineer')
WHERE name = 'Software roles';

UPDATE searches
SET keywords = array_remove(keywords, 'Platform Engineer')
WHERE name = 'Software roles';

UPDATE scrape_settings
SET allowed_roles = array_remove(array_remove(array_remove(array_remove(array_remove(
  allowed_roles, 'product_engineer'), 'growth_engineer'), 'platform_engineer'),
  'web_engineer'), 'forward_deployed')
WHERE id;
