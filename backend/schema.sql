CREATE DATABASE IF NOT EXISTS kisan_mitra CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE kisan_mitra;
CREATE TABLE IF NOT EXISTS users (
 id INT AUTO_INCREMENT PRIMARY KEY,
 full_name VARCHAR(120) NOT NULL,
 email VARCHAR(190) NOT NULL UNIQUE,
 password_hash VARCHAR(255) NOT NULL,
 role VARCHAR(20) NOT NULL DEFAULT 'farmer',
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS crop_reports (
 id INT AUTO_INCREMENT PRIMARY KEY,
 user_id INT NOT NULL,
 crop VARCHAR(100) NOT NULL,
 disease VARCHAR(200) NOT NULL,
 confidence DECIMAL(6,2) NOT NULL DEFAULT 0,
 severity VARCHAR(50),
 symptoms JSON,
 treatment JSON,
 prevention JSON,
 warning TEXT,
 recommendation TEXT,
 image_path VARCHAR(500),
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);


CREATE TABLE IF NOT EXISTS user_preferences (
 user_id INT PRIMARY KEY,
 language VARCHAR(30) NOT NULL DEFAULT 'en',
 email_address VARCHAR(190),
 email_enabled TINYINT(1) NOT NULL DEFAULT 0,
 weather_alerts TINYINT(1) NOT NULL DEFAULT 1,
 crop_reminders TINYINT(1) NOT NULL DEFAULT 1,
 notification_consent TINYINT(1) NOT NULL DEFAULT 0,
 latitude DECIMAL(10,7),
 longitude DECIMAL(10,7),
 updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
 FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS farm_calendar_events (
 id INT AUTO_INCREMENT PRIMARY KEY,
 user_id INT NOT NULL,
 title VARCHAR(160) NOT NULL,
 description TEXT,
 event_type VARCHAR(40) NOT NULL DEFAULT 'other',
 event_date DATE NOT NULL,
 reminder_days_before INT NOT NULL DEFAULT 1,
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
 INDEX idx_calendar_due (event_date, user_id)
);
CREATE TABLE IF NOT EXISTS notification_logs (
 id INT AUTO_INCREMENT PRIMARY KEY,
 user_id INT NOT NULL,
 event_id INT NULL,
 channel VARCHAR(20) NOT NULL,
 notification_type VARCHAR(40) NOT NULL,
 fingerprint VARCHAR(190) NOT NULL,
 status VARCHAR(20) NOT NULL,
 detail VARCHAR(500),
 sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
 INDEX idx_notification_dedupe (user_id, fingerprint, channel, status)
);


CREATE TABLE IF NOT EXISTS marketplace_profiles (user_id INT PRIMARY KEY, account_type VARCHAR(20) NOT NULL DEFAULT 'both', phone VARCHAR(30), state VARCHAR(100), district VARCHAR(150), latitude DECIMAL(10,7), longitude DECIMAL(10,7), created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS crop_listings (id INT AUTO_INCREMENT PRIMARY KEY, seller_id INT NOT NULL, commodity VARCHAR(120) NOT NULL, variety VARCHAR(120), quality_grade VARCHAR(80), quantity_quintals DECIMAL(12,2) NOT NULL, available_quintals DECIMAL(12,2) NOT NULL, asking_price DECIMAL(12,2) NOT NULL, state VARCHAR(100) NOT NULL, district VARCHAR(150) NOT NULL, pickup_location VARCHAR(255), description TEXT, status VARCHAR(20) NOT NULL DEFAULT 'active', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(seller_id) REFERENCES users(id) ON DELETE CASCADE, INDEX idx_listing_search(status,commodity,state,district));
CREATE TABLE IF NOT EXISTS marketplace_offers (id INT AUTO_INCREMENT PRIMARY KEY, listing_id INT NOT NULL, buyer_id INT NOT NULL, seller_id INT NOT NULL, quantity_quintals DECIMAL(12,2) NOT NULL, offered_price DECIMAL(12,2) NOT NULL, message TEXT, payment_method VARCHAR(30) NOT NULL DEFAULT 'direct_mutual', payment_terms VARCHAR(500), delivery_option VARCHAR(30) NOT NULL DEFAULT 'buyer_pickup', delivery_notes VARCHAR(500), last_action_by INT NULL, status VARCHAR(20) NOT NULL DEFAULT 'pending', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP, FOREIGN KEY(listing_id) REFERENCES crop_listings(id) ON DELETE CASCADE, FOREIGN KEY(buyer_id) REFERENCES users(id) ON DELETE CASCADE, FOREIGN KEY(seller_id) REFERENCES users(id) ON DELETE CASCADE, INDEX idx_offer_users(buyer_id,seller_id,status));
CREATE TABLE IF NOT EXISTS marketplace_messages (id INT AUTO_INCREMENT PRIMARY KEY, offer_id INT NOT NULL, sender_id INT NOT NULL, message TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(offer_id) REFERENCES marketplace_offers(id) ON DELETE CASCADE, FOREIGN KEY(sender_id) REFERENCES users(id) ON DELETE CASCADE, INDEX idx_market_messages(offer_id,id));
CREATE TABLE IF NOT EXISTS marketplace_orders (id INT AUTO_INCREMENT PRIMARY KEY, offer_id INT NOT NULL UNIQUE, listing_id INT NOT NULL, buyer_id INT NOT NULL, seller_id INT NOT NULL, quantity_quintals DECIMAL(12,2) NOT NULL, agreed_price DECIMAL(12,2) NOT NULL, payment_method VARCHAR(30) NOT NULL DEFAULT 'direct_mutual', payment_terms VARCHAR(500), delivery_option VARCHAR(30) NOT NULL DEFAULT 'buyer_pickup', delivery_notes VARCHAR(500), status VARCHAR(30) NOT NULL DEFAULT 'confirmed', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(offer_id) REFERENCES marketplace_offers(id), FOREIGN KEY(listing_id) REFERENCES crop_listings(id), FOREIGN KEY(buyer_id) REFERENCES users(id), FOREIGN KEY(seller_id) REFERENCES users(id));


-- Buyer–farmer direct chat and in-app notification tables
CREATE TABLE IF NOT EXISTS chat_conversations (id INT AUTO_INCREMENT PRIMARY KEY, listing_id INT NOT NULL, buyer_id INT NOT NULL, seller_id INT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP, UNIQUE KEY uq_listing_buyer (listing_id,buyer_id), FOREIGN KEY(listing_id) REFERENCES crop_listings(id) ON DELETE CASCADE, FOREIGN KEY(buyer_id) REFERENCES users(id) ON DELETE CASCADE, FOREIGN KEY(seller_id) REFERENCES users(id) ON DELETE CASCADE, INDEX idx_chat_participants (buyer_id,seller_id,updated_at));
CREATE TABLE IF NOT EXISTS chat_messages (id BIGINT AUTO_INCREMENT PRIMARY KEY, conversation_id INT NOT NULL, sender_id INT NOT NULL, message TEXT NOT NULL, is_read TINYINT(1) NOT NULL DEFAULT 0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(conversation_id) REFERENCES chat_conversations(id) ON DELETE CASCADE, FOREIGN KEY(sender_id) REFERENCES users(id) ON DELETE CASCADE, INDEX idx_chat_message_history (conversation_id,id), INDEX idx_chat_unread (conversation_id,is_read));
CREATE TABLE IF NOT EXISTS chat_notifications (id BIGINT AUTO_INCREMENT PRIMARY KEY, user_id INT NOT NULL, conversation_id INT NOT NULL, message_id BIGINT NOT NULL, title VARCHAR(160) NOT NULL, body VARCHAR(255) NOT NULL, is_read TINYINT(1) NOT NULL DEFAULT 0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE, FOREIGN KEY(conversation_id) REFERENCES chat_conversations(id) ON DELETE CASCADE, FOREIGN KEY(message_id) REFERENCES chat_messages(id) ON DELETE CASCADE, INDEX idx_chat_notifications_user (user_id,is_read,created_at));
