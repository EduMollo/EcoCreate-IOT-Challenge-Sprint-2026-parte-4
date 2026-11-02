package br.com.fiap.clyvovet.service;

import java.net.URI;
import java.net.HttpURLConnection;
import java.nio.charset.StandardCharsets;
import org.springframework.stereotype.Component;

/** Bounded HTTP transport; no connection or selector is created during app startup. */
@Component
public class CopilotGateway {
    public String analisar(String url,String token,String payload) throws Exception {
        HttpURLConnection connection=(HttpURLConnection)URI.create(url+"/v1/analyze").toURL().openConnection();
        try {
            connection.setConnectTimeout(5000);connection.setReadTimeout(55000);
            connection.setRequestMethod("POST");connection.setDoOutput(true);
            connection.setRequestProperty("Authorization","Bearer "+token);
            connection.setRequestProperty("Content-Type","application/json");
            try(var out=connection.getOutputStream()) {out.write(payload.getBytes(StandardCharsets.UTF_8));}
            if(connection.getResponseCode()!=200) throw new IllegalStateException("AI service unavailable");
            try(var in=connection.getInputStream()) {
                byte[] bytes=in.readNBytes(256*1024+1);
                if(bytes.length>256*1024) throw new IllegalStateException("AI response too large");
                return new String(bytes,StandardCharsets.UTF_8);
            }
        } finally {connection.disconnect();}
    }
}
