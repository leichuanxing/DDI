CREATE DATABASE IF NOT EXISTS ddi_system CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS powerdns CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS kea CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
GRANT ALL PRIVILEGES ON ddi_system.* TO 'ddi'@'%';
GRANT ALL PRIVILEGES ON powerdns.* TO 'ddi'@'%';
GRANT ALL PRIVILEGES ON kea.* TO 'ddi'@'%';
FLUSH PRIVILEGES;

USE powerdns;
CREATE TABLE IF NOT EXISTS domains (id INT AUTO_INCREMENT, name VARCHAR(255) NOT NULL, master VARCHAR(128) DEFAULT NULL, last_check INT DEFAULT NULL, type VARCHAR(8) NOT NULL, notified_serial INT DEFAULT NULL, account VARCHAR(40) DEFAULT NULL, options TEXT DEFAULT NULL, catalog VARCHAR(255) DEFAULT NULL, PRIMARY KEY (id), UNIQUE KEY name_index (name));
CREATE TABLE IF NOT EXISTS records (id BIGINT AUTO_INCREMENT, domain_id INT DEFAULT NULL, name VARCHAR(255) DEFAULT NULL, type VARCHAR(10) DEFAULT NULL, content TEXT DEFAULT NULL, ttl INT DEFAULT NULL, prio INT DEFAULT NULL, disabled TINYINT(1) DEFAULT 0, ordername VARCHAR(255) BINARY DEFAULT NULL, auth TINYINT(1) DEFAULT 1, PRIMARY KEY (id), KEY nametype_index (name,type), KEY domain_id (domain_id));
CREATE TABLE IF NOT EXISTS supermasters (ip VARCHAR(64) NOT NULL, nameserver VARCHAR(255) NOT NULL, account VARCHAR(40) NOT NULL, PRIMARY KEY (ip,nameserver));
CREATE TABLE IF NOT EXISTS comments (id INT AUTO_INCREMENT, domain_id INT NOT NULL, name VARCHAR(255) NOT NULL, type VARCHAR(10) NOT NULL, modified_at INT NOT NULL, account VARCHAR(40) DEFAULT NULL, comment TEXT NOT NULL, PRIMARY KEY (id), KEY comments_domain_id_idx (domain_id), KEY comments_name_type_idx (name,type));
CREATE TABLE IF NOT EXISTS domainmetadata (id INT AUTO_INCREMENT, domain_id INT NOT NULL, kind VARCHAR(32), content TEXT, PRIMARY KEY (id), KEY domainmetadata_idx (domain_id, kind));
CREATE TABLE IF NOT EXISTS cryptokeys (id INT AUTO_INCREMENT, domain_id INT NOT NULL, flags INT NOT NULL, active BOOL, published BOOL DEFAULT 1, content TEXT, PRIMARY KEY(id), KEY domainidindex (domain_id));
CREATE TABLE IF NOT EXISTS tsigkeys (id INT AUTO_INCREMENT, name VARCHAR(255), algorithm VARCHAR(50), secret VARCHAR(255), PRIMARY KEY (id), UNIQUE KEY namealgoindex (name, algorithm));
