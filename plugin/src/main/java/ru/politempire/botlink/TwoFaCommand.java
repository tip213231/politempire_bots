package ru.politempire.botlink;

import org.bukkit.command.Command;
import org.bukkit.command.CommandExecutor;
import org.bukkit.command.CommandSender;
import org.bukkit.entity.Player;
import org.jetbrains.annotations.NotNull;

/**
 * /2fa <код> - проверка кода через API бота и разморозка игрока.
 */
public final class TwoFaCommand implements CommandExecutor {

    private final BotLinkPlugin plugin;
    private final ApiClient api;
    private final FreezeManager freeze;

    public TwoFaCommand(BotLinkPlugin plugin, ApiClient api, FreezeManager freeze) {
        this.plugin = plugin;
        this.api = api;
        this.freeze = freeze;
    }

    @Override
    public boolean onCommand(@NotNull CommandSender sender, @NotNull Command command,
                             @NotNull String label, String @NotNull [] args) {
        if (!(sender instanceof Player player)) {
            sender.sendMessage("Только для игроков.");
            return true;
        }

        if (!freeze.isFrozen(player.getUniqueId())) {
            player.sendMessage(plugin.msg("2fa-not-required"));
            return true;
        }

        if (args.length != 1) {
            player.sendMessage(plugin.msg("2fa-usage"));
            return true;
        }

        String code = args[0].trim();

        api.verify2fa(player.getName(), code).thenAccept(ok ->
                plugin.getServer().getScheduler().runTask(plugin, () -> {
                    if (!player.isOnline()) return;

                    if (ok) {
                        freeze.unfreeze(player);
                        player.sendMessage(plugin.msg("2fa-success"));
                        return;
                    }

                    int left = freeze.decrementAttempts(player.getUniqueId());
                    if (left <= 0) {
                        freeze.discard(player.getUniqueId());
                        player.kick(plugin.msg("2fa-kick-attempts"));
                    } else {
                        player.sendMessage(plugin.msg("2fa-wrong", "%attempts%", String.valueOf(left)));
                    }
                })
        );
        return true;
    }
}
