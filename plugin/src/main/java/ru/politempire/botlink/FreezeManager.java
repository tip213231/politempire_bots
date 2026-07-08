package ru.politempire.botlink;

import org.bukkit.entity.Player;
import org.bukkit.potion.PotionEffect;
import org.bukkit.potion.PotionEffectType;
import org.bukkit.scheduler.BukkitTask;

import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Хранит игроков, ожидающих подтверждения 2FA:
 * блокирует движение/чат/команды до успешного /2fa <код>.
 */
public final class FreezeManager {

    public static final class Pending {
        volatile int attemptsLeft;
        volatile BukkitTask timeoutTask;

        Pending(int attemptsLeft) {
            this.attemptsLeft = attemptsLeft;
        }
    }

    private final Map<UUID, Pending> pending = new ConcurrentHashMap<>();

    public void freeze(Player player, int maxAttempts, BukkitTask timeoutTask) {
        Pending p = new Pending(maxAttempts);
        p.timeoutTask = timeoutTask;
        pending.put(player.getUniqueId(), p);
        player.addPotionEffect(new PotionEffect(
                PotionEffectType.BLINDNESS, PotionEffect.INFINITE_DURATION, 0, false, false));
        player.setInvulnerable(true);
    }

    public boolean isFrozen(UUID uuid) {
        return pending.containsKey(uuid);
    }

    /** @return оставшиеся попытки после декремента, либо -1 если игрок не заморожен */
    public int decrementAttempts(UUID uuid) {
        Pending p = pending.get(uuid);
        if (p == null) return -1;
        return --p.attemptsLeft;
    }

    public void unfreeze(Player player) {
        Pending p = pending.remove(player.getUniqueId());
        if (p != null && p.timeoutTask != null) {
            p.timeoutTask.cancel();
        }
        player.removePotionEffect(PotionEffectType.BLINDNESS);
        player.setInvulnerable(false);
    }

    /** Убирает игрока из ожидания без снятия эффектов (например, при выходе). */
    public void discard(UUID uuid) {
        Pending p = pending.remove(uuid);
        if (p != null && p.timeoutTask != null) {
            p.timeoutTask.cancel();
        }
    }
}
