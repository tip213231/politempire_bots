package ru.politempire.botlink;

import net.kyori.adventure.text.Component;
import net.kyori.adventure.text.serializer.legacy.LegacyComponentSerializer;
import org.bukkit.plugin.java.JavaPlugin;

/**
 * PolitEmpireBotLink - связывает Paper-сервер с ботом PolitEmpire:
 * - при входе игрока вызывает /api/player/join (2FA + учёт времени)
 * - блокирует игрока до подтверждения кода командой /2fa
 * - при выходе вызывает /api/player/quit (закрытие игровой сессии)
 */
public final class BotLinkPlugin extends JavaPlugin {

    private static final LegacyComponentSerializer LEGACY =
            LegacyComponentSerializer.legacyAmpersand();

    private ApiClient api;
    private FreezeManager freeze;

    @Override
    public void onEnable() {
        saveDefaultConfig();

        String url = getConfig().getString("api-url", "http://127.0.0.1:8180");
        String secret = getConfig().getString("api-secret", "");
        int timeout = getConfig().getInt("http-timeout-seconds", 5);

        if (secret == null || secret.isEmpty() || secret.equals("CHANGE_ME")) {
            getLogger().severe("api-secret не настроен в config.yml! Плагин отключён.");
            getServer().getPluginManager().disablePlugin(this);
            return;
        }

        this.api = new ApiClient(url, secret, timeout, getLogger());
        this.freeze = new FreezeManager();

        getServer().getPluginManager().registerEvents(
                new PlayerListener(this, api, freeze), this);

        var cmd = getCommand("2fa");
        if (cmd != null) {
            cmd.setExecutor(new TwoFaCommand(this, api, freeze));
        }

        getLogger().info("PolitEmpireBotLink включён. API: " + url);
    }

    @Override
    public void onDisable() {
        // Закрываем сессии всех онлайн-игроков, чтобы бот корректно учёл время
        if (api != null) {
            getServer().getOnlinePlayers().forEach(p -> api.playerQuit(p.getName()));
        }
        getLogger().info("PolitEmpireBotLink выключен.");
    }

    /** Сообщение из config.yml с префиксом и &-цветами. */
    public Component msg(String key, String... replacements) {
        String prefix = getConfig().getString("messages.prefix", "");
        String text = getConfig().getString("messages." + key, key);
        for (int i = 0; i + 1 < replacements.length; i += 2) {
            text = text.replace(replacements[i], replacements[i + 1]);
        }
        return LEGACY.deserialize(prefix + text);
    }
}
