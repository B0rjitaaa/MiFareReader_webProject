function mifareApp() {
  return {
    status: { reader: null, card: null },
    connected: false,
    reading: false,
    keysText: "",
    error: "",
    result: null,
    kindLabels: { manufacturer: "Fabricante", data: "Datos", trailer: "Trailer" },

    connect() {
      const scheme = location.protocol === "https:" ? "wss" : "ws";
      const socket = new WebSocket(`${scheme}://${location.host}/ws/status`);
      socket.onopen = () => { this.connected = true; };
      socket.onmessage = (event) => {
        this.status = JSON.parse(event.data);
        const uid = this.status.card?.uid;
        if (uid && this.result && uid !== this.result.uid) this.result = null;
      };
      socket.onclose = () => {
        this.connected = false;
        this.status = { reader: null, card: null };
        setTimeout(() => this.connect(), 2000);
      };
    },

    parseKeys() {
      const keys = this.keysText.split(/[\s,]+/).filter(Boolean);
      const invalid = keys.find((key) => !/^[0-9A-Fa-f]{12}$/.test(key));
      if (invalid) throw new Error(`Clave no válida: ${invalid}`);
      return keys;
    },

    async read() {
      this.error = "";
      this.reading = true;
      try {
        const response = await fetch("/api/read", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ keys: this.parseKeys() }),
        });
        const body = await response.json();
        if (!response.ok) {
          throw new Error(typeof body.detail === "string" ? body.detail : "Petición no válida");
        }
        this.result = body;
      } catch (error) {
        this.error = error.message;
      } finally {
        this.reading = false;
      }
    },

    readableSectors() {
      return this.result.sectors.filter((sector) => sector.key).length;
    },

    toAscii(data) {
      if (!data) return "";
      return data.split(" ").map((byte) => {
        const code = parseInt(byte, 16);
        return code >= 32 && code < 127 ? String.fromCharCode(code) : "·";
      }).join("");
    },
  };
}
