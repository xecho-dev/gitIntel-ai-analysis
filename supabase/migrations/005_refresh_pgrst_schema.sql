-- Refresh PostgREST schema cache so it picks up the admin_tokens/admin_users FK relationship
notify pgrst, 'reload';
