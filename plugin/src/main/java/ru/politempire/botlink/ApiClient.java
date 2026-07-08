package ru.politempire.botlink;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.concurrent.CompletableFuture;
import java.util.logging.Logger;

/**
 * Асинхронный HTTP-клиент к API бота (bot/api/server.py).
 * Все запросы уходят с заголовком X-Api-Secret.
 */
public final class ApiClient {

    /** Результат /api/player/join */
    public record JoinResult(boolean require2fa, boolean banned, String reason, boolean apiError) {}

    private final HttpClient http;
    private final String baseUrl;
    private final String secret;
    private final Duration timeout;
    private final Logger log;

    public ApiClient(String baseUrl, String secret, int timeoutSeconds, Logger log) {
        this.baseUrl = baseUrl.endsWith("/") ? baseUrl.substring(0, baseUrl.length() - 1) : baseUrl;
        this.secret = secret;
        this.timeout = Duration.ofSeconds(timeoutSeconds);
        this.log = log;
        this.http = HttpClient.newBuilder()
                .connectTimeout(this.timeout)
                .build();
    }

    public CompletableFuture<JoinResult> playerJoin(String username, String ip) {
        String body = "{\"username\":" + jsonStr(username) + ",\"ip\":" + jsonStr(ip) + "}";
        return post("/api/player/join", body).thenApply(resp -> {
            if (resp == null) {
                return new JoinResult(false, false, "", true);
            }
            boolean require = jsonBool(resp, "require_2fa");
            boolean banned = jsonBool(resp, "banned");
            String reason = jsonString(resp, "reason");
            return new JoinResult(require, banned, reason, false);
        });
    }

    public CompletableFuture<Boolean> verify2fa(String username, String code) {
        String body = "{\"username\":" + jsonStr(username) + ",\"code\":" + jsonStr(code) + "}";
        return post("/api/2fa/verify", body).thenApply(resp -> resp != null && jsonBool(resp, "ok"));
    }

    public void playerQuit(String username) {
        String body = "{\"username\":" + jsonStr(username) + "}";
        post("/api/player/quit", body); // fire-and-forget
    }

    private CompletableFuture<String> post(String path, String jsonBody) {
        HttpRequest request = HttpRequest.newBuilder()
                .uri(URI.create(baseUrl + path))
                .timeout(timeout)
                .header("Content-Type", "application/json")
                .header("X-Api-Secret", secret)
                .POST(HttpRequest.BodyPublishers.ofString(jsonBody))
                .build();
        return http.sendAsync(request, HttpResponse.BodyHandlers.ofString())
                .handle((resp, err) -> {
                    if (err != null) {
                        log.warning("Bot API " + path + " failed: " + err.getMessage());
                        return null;
                    }
                    if (resp.statusCode() != 200) {
                        log.warning("Bot API " + path + " returned HTTP " + resp.statusCode());
                        return null;
                    }
                    return resp.body();
                });
    }

    // --- минимальный разбор плоского JSON-ответа без зависимостей ---

    private static boolean jsonBool(String json, String key) {
        var m = java.util.regex.Pattern
                .compile("\"" + java.util.regex.Pattern.quote(key) + "\"\\s*:\\s*(true|false)")
                .matcher(json);
        return m.find() && m.group(1).equals("true");
    }

    private static String jsonString(String json, String key) {
        var m = java.util.regex.Pattern
                .compile("\"" + java.util.regex.Pattern.quote(key) + "\"\\s*:\\s*\"((?:[^\"\\\\]|\\\\.)*)\"")
                .matcher(json);
        if (!m.find()) return "";
        return m.group(1)
                .replace("\\\"", "\"")
                .replace("\\\\", "\\")
                .replace("\\n", "\n");
    }

    private static String jsonStr(String value) {
        if (value == null) return "null";
        StringBuilder sb = new StringBuilder("\"");
        for (char c : value.toCharArray()) {
            switch (c) {
                case '"' -> sb.append("\\\"");
                case '\\' -> sb.append("\\\\");
                case '\n' -> sb.append("\\n");
                case '\r' -> sb.append("\\r");
                case '\t' -> sb.append("\\t");
                default -> {
                    if (c < 0x20) {
                        sb.append(String.format("\\u%04x", (int) c));
                    } else {
                        sb.append(c);
                    }
                }
            }
        }
        return sb.append('"').toString();
    }
}
