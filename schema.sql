-- Схема таблиц бота PolitEmpire.
-- Запустите этот файл ОДИН РАЗ под пользователем с правами CREATE
-- (например, root в DBeaver), выбрав базу polit_empire.
--
-- Существующие таблицы (users, bot_admins, bot_sessions) НЕ затрагиваются.
-- Все таблицы бота создаются с префиксом bot_ и только если их ещё нет.

USE polit_empire;

-- Настройки бота (например, обязательная 2FA)
CREATE TABLE IF NOT EXISTS bot_settings (
    `key` VARCHAR(64) PRIMARY KEY,
    `value` VARCHAR(255) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Состояние 2FA по игроку (привязка к users.id)
CREATE TABLE IF NOT EXISTS bot_2fa (
    user_id INT PRIMARY KEY,
    enabled TINYINT(1) NOT NULL DEFAULT 0,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Одноразовые коды 2FA
CREATE TABLE IF NOT EXISTS bot_2fa_codes (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    code VARCHAR(8) NOT NULL,
    expires_at DATETIME NOT NULL,
    used TINYINT(1) NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_2fa_user (user_id, used, expires_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Персональные инвайт-ссылки Discord
CREATE TABLE IF NOT EXISTS bot_discord_invites (
    invite_code VARCHAR(32) PRIMARY KEY,
    discord_id BIGINT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_inv_discord (discord_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Рефералы: кто кого пригласил и статус выполнения условий
CREATE TABLE IF NOT EXISTS bot_referrals (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    invited_discord_id BIGINT NOT NULL UNIQUE,
    inviter_discord_id BIGINT NOT NULL,
    invite_code VARCHAR(32) NOT NULL,
    mc_username VARCHAR(80) DEFAULT NULL,
    playtime_seconds INT NOT NULL DEFAULT 0,
    joined_discord_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed TINYINT(1) NOT NULL DEFAULT 0,
    rewarded TINYINT(1) NOT NULL DEFAULT 0,
    completed_at DATETIME DEFAULT NULL,
    INDEX idx_ref_inviter (inviter_discord_id),
    INDEX idx_ref_mc (mc_username)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Привязка ника MC к Discord-аккаунту (для рефералки)
CREATE TABLE IF NOT EXISTS bot_discord_links (
    discord_id BIGINT PRIMARY KEY,
    mc_username VARCHAR(80) NOT NULL,
    linked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_link_mc (mc_username)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Журнал начислений/списаний DC Coin
CREATE TABLE IF NOT EXISTS bot_balance_log (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    mc_username VARCHAR(80) NOT NULL,
    amount INT NOT NULL,
    reason VARCHAR(255) NOT NULL,
    actor VARCHAR(80) NOT NULL DEFAULT 'system',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_bal_user (mc_username)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Журнал авторизаций (входы на сервер, 2FA успех/неуспех)
CREATE TABLE IF NOT EXISTS bot_auth_log (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    mc_username VARCHAR(80) NOT NULL,
    event VARCHAR(32) NOT NULL,
    ip VARCHAR(45) DEFAULT NULL,
    success TINYINT(1) NOT NULL DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_auth_user (mc_username),
    INDEX idx_auth_event (event)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Журнал действий администрации
CREATE TABLE IF NOT EXISTS bot_admin_log (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    admin_telegram_id BIGINT NOT NULL,
    action VARCHAR(64) NOT NULL,
    target VARCHAR(120) DEFAULT NULL,
    details TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Журнал вступлений в Discord по инвайтам
CREATE TABLE IF NOT EXISTS bot_join_log (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    discord_id BIGINT NOT NULL,
    invite_code VARCHAR(32) DEFAULT NULL,
    inviter_discord_id BIGINT DEFAULT NULL,
    counted TINYINT(1) NOT NULL DEFAULT 0,
    note VARCHAR(255) DEFAULT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Активные игровые сессии (для учёта 10 минут)
CREATE TABLE IF NOT EXISTS bot_play_sessions (
    mc_username VARCHAR(80) PRIMARY KEY,
    joined_at DATETIME NOT NULL,
    ip VARCHAR(45) DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
