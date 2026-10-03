-- migrate:up
alter table conversations alter column id set default uuidv7();
alter table messages alter column id set default uuidv7();
alter table documents alter column id set default uuidv7();
alter table chunks alter column id set default uuidv7();

-- migrate:down
alter table conversations alter column id set default gen_random_uuid();
alter table messages alter column id set default gen_random_uuid();
alter table documents alter column id set default gen_random_uuid();
alter table chunks alter column id set default gen_random_uuid();
