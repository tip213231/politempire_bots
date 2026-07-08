package ru.politempire.botlink;

import io.papermc.paper.event.player.AsyncChatEvent;
import net.kyori.adventure.text.Component;
import org.bukkit.Location;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.EventPriority;
import org.bukkit.event.Listener;
import org.bukkit.event.block.BlockBreakEvent;
import org.bukkit.event.block.BlockPlaceEvent;
import org.bukkit.event.entity.EntityDamageByEntityEvent;
import org.bukkit.event.player.PlayerCommandPreprocessEvent;
import org.bukkit.event.player.PlayerDropItemEvent;
import org.bukkit.event.player.PlayerInteractEvent;
import org.bukkit.event.player.PlayerJoinEvent;
import org.bukkit.event.player.PlayerMoveEvent;
import org.bukkit.event.player.PlayerQuitEvent;
import org.bukkit.scheduler.BukkitTask;

import java.net.InetSocketAddress;

/**
 * Обработка входа/выхода: обращение к API бота, заморозка до подтверждения 2FA.
 */
public final class PlayerListener implements Listener {

    private final BotLinkPlugin plugin;
    private final ApiClient api;
    private final FreezeManager freeze;

    public PlayerListener(BotLinkPlugin plugin, ApiClient api, FreezeManager freeze) {
        this.plugin = plugin;
        this.api = api;
        this.freeze = freeze;
    }

    @EventHandler(priority = EventPriority.MONITOR)
    public void onJoin(PlayerJoinEvent event) {
        Player player = event.getPlayer();
        String username = player.getName();
        InetSocketAddress addr = player.getAddress();
        String ip = addr != null ? addr.getAddress().getHostAddress() : null;

        api.playerJoin(username, ip).thenAccept(result ->
                // Возвращаемся в основной поток сервера
                plugin.getServer().getScheduler().runTask(plugin, () -> {
                    if (!player.isOnline()) return;

                    if (result.apiError()) {
                        // API недоступен - не блокируем игрока, только предупреждаем в лог
                        plugin.getLogger().warning("Bot API unavailable, skipping 2FA for " + username);
                        return;
                    }

                    if (result.banned()) {
                        String reason = result.reason().isEmpty() ? "не указана" : result.reason();
                        player.kick(plugin.msg("banned-kick", "%reason%", reason));
                        return;
                    }

                    if (result.require2fa()) {
                        startTwoFa(player);
                    }
                })
        );
    }

    private void startTwoFa(Player player) {
        int timeoutTicks = plugin.getConfig().getInt("2fa.timeout-seconds", 300) * 20;
        int maxAttempts = plugin.getConfig().getInt("2fa.max-attempts", 3);

        BukkitTask timeoutTask = plugin.getServer().getScheduler().runTaskLater(plugin, () -> {
            if (player.isOnline() && freeze.isFrozen(player.getUniqueId())) {
                freeze.discard(player.getUniqueId());
                player.kick(plugin.msg("2fa-kick-timeout"));
            }
        }, timeoutTicks);

        freeze.freeze(player, maxAttempts, timeoutTask);
        player.sendMessage(plugin.msg("need-2fa"));
    }

    @EventHandler(priority = EventPriority.MONITOR)
    public void onQuit(PlayerQuitEvent event) {
        freeze.discard(event.getPlayer().getUniqueId());
        api.playerQuit(event.getPlayer().getName());
    }

    // ---------- Блокировки во время ожидания 2FA ----------

    @EventHandler(ignoreCancelled = true)
    public void onMove(PlayerMoveEvent event) {
        if (!freeze.isFrozen(event.getPlayer().getUniqueId())) return;
        Location from = event.getFrom();
        Location to = event.getTo();
        // Разрешаем поворот головы, запрещаем смену позиции
        if (from.getX() != to.getX() || from.getY() != to.getY() || from.getZ() != to.getZ()) {
            event.setTo(new Location(from.getWorld(), from.getX(), from.getY(), from.getZ(),
                    to.getYaw(), to.getPitch()));
        }
    }

    @EventHandler(ignoreCancelled = true)
    public void onCommand(PlayerCommandPreprocessEvent event) {
        if (!freeze.isFrozen(event.getPlayer().getUniqueId())) return;
        String cmd = event.getMessage().toLowerCase();
        if (cmd.startsWith("/2fa ") || cmd.equals("/2fa")) return;
        event.setCancelled(true);
        event.getPlayer().sendMessage(plugin.msg("frozen"));
    }

    @EventHandler(ignoreCancelled = true)
    public void onChat(AsyncChatEvent event) {
        if (freeze.isFrozen(event.getPlayer().getUniqueId())) {
            event.setCancelled(true);
            event.getPlayer().sendMessage(plugin.msg("frozen"));
        }
    }

    @EventHandler(ignoreCancelled = true)
    public void onInteract(PlayerInteractEvent event) {
        if (freeze.isFrozen(event.getPlayer().getUniqueId())) {
            event.setCancelled(true);
        }
    }

    @EventHandler(ignoreCancelled = true)
    public void onBreak(BlockBreakEvent event) {
        if (freeze.isFrozen(event.getPlayer().getUniqueId())) {
            event.setCancelled(true);
        }
    }

    @EventHandler(ignoreCancelled = true)
    public void onPlace(BlockPlaceEvent event) {
        if (freeze.isFrozen(event.getPlayer().getUniqueId())) {
            event.setCancelled(true);
        }
    }

    @EventHandler(ignoreCancelled = true)
    public void onDrop(PlayerDropItemEvent event) {
        if (freeze.isFrozen(event.getPlayer().getUniqueId())) {
            event.setCancelled(true);
        }
    }

    @EventHandler(ignoreCancelled = true)
    public void onDamageByEntity(EntityDamageByEntityEvent event) {
        if (event.getDamager() instanceof Player damager
                && freeze.isFrozen(damager.getUniqueId())) {
            event.setCancelled(true);
        }
    }

    @SuppressWarnings("unused")
    private static Component unused() {
        return Component.empty();
    }
}
