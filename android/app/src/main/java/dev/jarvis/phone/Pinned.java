package dev.jarvis.phone;

import java.net.URL;
import java.security.MessageDigest;
import java.security.cert.CertificateException;
import java.security.cert.X509Certificate;

import javax.net.ssl.HttpsURLConnection;
import javax.net.ssl.SSLContext;
import javax.net.ssl.TrustManager;
import javax.net.ssl.X509TrustManager;

/** Opens an HTTPS connection to the PC that accepts exactly one thing: the public key confirmed during setup. Nothing else is trusted. */
final class Pinned {
    private Pinned() { }

    static String spki(X509Certificate cert) throws Exception {
        byte[] d = MessageDigest.getInstance("SHA-256").digest(cert.getPublicKey().getEncoded());
        StringBuilder sb = new StringBuilder();
        for (byte b : d) sb.append(String.format("%02x", b));
        return sb.toString();
    }

    static HttpsURLConnection open(String address, final String pin, String path) throws Exception {
        TrustManager pinned = new X509TrustManager() {
            @Override public void checkClientTrusted(X509Certificate[] c, String t) throws CertificateException { throw new CertificateException("no client certificates"); }

            @Override
            public void checkServerTrusted(X509Certificate[] chain, String t) throws CertificateException {
                try {
                    if (!spki(chain[0]).equals(pin)) throw new CertificateException("the PC's key is not the one that was confirmed");
                } catch (CertificateException e) {
                    throw e;
                } catch (Exception e) {
                    throw new CertificateException(e);
                }
            }

            @Override public X509Certificate[] getAcceptedIssuers() { return new X509Certificate[0]; }
        };
        SSLContext ctx = SSLContext.getInstance("TLS");
        ctx.init(null, new TrustManager[]{pinned}, null);
        HttpsURLConnection c = (HttpsURLConnection) new URL("https://" + address + path).openConnection();
        c.setSSLSocketFactory(ctx.getSocketFactory());
        c.setHostnameVerifier((h, s) -> true);                  // the pinned key is what identifies the PC, not its address
        c.setConnectTimeout(8000);
        return c;
    }
}
