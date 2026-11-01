function mifareApp() {
  return {
    status: { reader: null, card: null },
    connected: false,
    reading: false,
    keysText: "",
    error: "",
    result: null,
    viewingName: "",
    destination: "",
    cardName: "",
    saving: false,
    saveMessage: "",
    saveError: "",
    savedCards: [],
    editingId: null,
    editName: "",
    kindLabels: { manufacturer: "Fabricante", data: "Datos", trailer: "Trailer" },

    connect() {
      this.loadSavedCards();
      const scheme = location.protocol === "https:" ? "wss" : "ws";
      const socket = new WebSocket(`${scheme}://${location.host}/ws/status`);
      socket.onopen = () => { this.connected = true; };
      socket.onmessage = (event) => {
        this.status = JSON.parse(event.data);
        const uid = this.status.card?.uid;
        if (uid && this.result && !this.viewingName && uid !== this.result.uid) this.result = null;
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
        this.viewingName = "";
        this.destination = "";
        this.saveMessage = "";
        this.cardName = `Tarjeta ${(body.uid || "").replaceAll(" ", "")}`.trim();
      } catch (error) {
        this.error = error.message;
      } finally {
        this.reading = false;
      }
    },

    async requestJson(url, options) {
      const response = await fetch(url, options);
      const body = await response.json();
      if (!response.ok) {
        throw new Error(typeof body.detail === "string" ? body.detail : "Petición no válida");
      }
      return body;
    },

    async loadSavedCards() {
      try {
        this.savedCards = await this.requestJson("/api/cards");
      } catch (error) {
        this.error = error.message;
      }
    },

    async save() {
      this.saveError = "";
      this.saveMessage = "";
      this.saving = true;
      const name = this.cardName.trim();
      try {
        if (this.destination === "mint") {
          await this.requestJson("/api/cards", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name, uid: this.result.uid }),
          });
          await this.loadSavedCards();
          this.saveMessage = `Guardada en el Mint como «${name}».`;
        } else {
          this.downloadJson({ name, ...this.result }, name);
          this.saveMessage = "Archivo enviado a las descargas del navegador.";
        }
      } catch (error) {
        this.saveError = error.message;
      } finally {
        this.saving = false;
      }
    },

    async view(card) {
      this.error = "";
      try {
        this.result = await this.requestJson(`/api/cards/${card.id}`);
        this.viewingName = card.name;
        window.scrollTo({ top: 0 });
      } catch (error) {
        this.error = error.message;
      }
    },

    async downloadSaved(card) {
      this.error = "";
      try {
        this.downloadJson(await this.requestJson(`/api/cards/${card.id}`), card.name);
      } catch (error) {
        this.error = error.message;
      }
    },

    downloadJson(data, name) {
      const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }));
      const link = document.createElement("a");
      link.href = url;
      link.download = `${name.replace(/[^\p{L}\p{N}_-]+/gu, "_")}.json`;
      link.click();
      URL.revokeObjectURL(url);
    },

    formatDate(value) {
      return value ? new Date(value).toLocaleString("es-ES") : "";
    },

    startRename(card) {
      this.editingId = card.id;
      this.editName = card.name;
      this.error = "";
    },

    cancelRename() {
      this.editingId = null;
      this.editName = "";
    },

    async confirmRename(card) {
      const name = this.editName.trim();
      if (!name) return;
      this.error = "";
      try {
        await this.requestJson(`/api/cards/${card.id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name }),
        });
        if (this.viewingName === card.name) this.viewingName = name;
        this.editingId = null;
        await this.loadSavedCards();
      } catch (error) {
        this.error = error.message;
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
