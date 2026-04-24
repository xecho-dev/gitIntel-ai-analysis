-- ============================================================
-- Seed script for admin_users
-- Run AFTER 004_add_admin_users.sql
--
-- DEFAULT CREDENTIALS:
--   Username: admin
--   Password: gitintel2024
--
-- HOW TO GENERATE YOUR OWN HASH:
--   python3 -c "import bcrypt; print(bcrypt.hashpw(b'your_password', bcrypt.gensalt()).decode())"
--   pip install bcrypt  (if bcrypt is not installed)
--
-- Then update the password_hash below with the generated hash.
-- ============================================================

-- Example: update the placeholder hash (run the python command above to generate)
-- update public.admin_users
-- set password_hash = 'YOUR_GENERATED_HASH_HERE'
-- where username = 'admin';

-- Ensure admin user exists with the default password hash
-- Default password: gitintel2024
insert into public.admin_users (username, password_hash, nickname, role)
values (
    'admin',
    'xxxx',
    'Administrator',
    'super_admin'
) on conflict (username) do update
set password_hash = excluded.password_hash,
    nickname = excluded.nickname,
    role = excluded.role,
    updated_at = now();

