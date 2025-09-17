INSERT INTO users(email, password_hash, display_name, created_at)
  VALUES ('test@example.com', crypt('Password123!', gen_salt('bf', 12)), 'Test User', now())
ON CONFLICT (email)
  DO UPDATE SET
    display_name = EXCLUDED.display_name;

