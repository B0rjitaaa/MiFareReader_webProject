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
    tab: "reader",
    leftId: "",
    rightId: "",
    leftCard: null,
    rightCard: null,
    compareError: "",
    showEqual: false,
    diffResult: null,
    writeMode: "text",
    writeText: "",
    writeHex: "",
    writeStart: 1,
    writeKeys: "",
    writePlan: null,
    writeResults: null,
    writeConfirm: false,
    writeError: "",
    writing: false,
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

    parseKeyText(text) {
      const keys = text.split(/[\s,]+/).filter(Boolean);
      const invalid = keys.find((key) => !/^[0-9A-Fa-f]{12}$/.test(key));
      if (invalid) throw new Error(`Clave no válida: ${invalid}`);
      return keys;
    },

    parseKeys() {
      return this.parseKeyText(this.keysText);
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
        this.tab = "reader";
        window.scrollTo({ top: 0 });
      } catch (error) {
        this.error = error.message;
      }
    },

    async downloadDump(card) {
      this.error = "";
      try {
        const response = await fetch(`/api/cards/${card.id}/dump`);
        if (!response.ok) throw new Error("No se pudo generar el .dump");
        const url = URL.createObjectURL(await response.blob());
        const link = document.createElement("a");
        link.href = url;
        link.download = `${card.name.replace(/[^\p{L}\p{N}_-]+/gu, "_")}.bin`;
        link.click();
        URL.revokeObjectURL(url);
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

    async loadSide(side) {
      this.compareError = "";
      const id = side === "left" ? this.leftId : this.rightId;
      if (!id) {
        if (side === "left") this.leftCard = null; else this.rightCard = null;
        this.computeDiff();
        return;
      }
      try {
        const card = await this.requestJson(`/api/cards/${id}`);
        if (side === "left") this.leftCard = card; else this.rightCard = card;
        this.computeDiff();
      } catch (error) {
        this.compareError = error.message;
      }
    },

    computeDiff() {
      if (!this.leftCard || !this.rightCard) { this.diffResult = null; return; }
      const index = (card) => {
        const map = new Map();
        (card.sectors || []).forEach((sector) =>
          (sector.blocks || []).forEach((block) =>
            map.set(block.block, { sector: sector.sector, kind: block.kind, data: block.data })));
        return map;
      };
      const left = index(this.leftCard);
      const right = index(this.rightCard);
      const numbers = [...new Set([...left.keys(), ...right.keys()])].sort((a, b) => a - b);
      const sectors = new Map();
      let changed = 0;
      let compared = 0;
      for (const number of numbers) {
        const l = left.get(number);
        const r = right.get(number);
        const sector = l?.sector ?? r?.sector;
        const kind = l?.kind ?? r?.kind;
        const ld = l?.data ?? null;
        const rd = r?.data ?? null;
        let status;
        const bytes = [];
        if (ld === null || rd === null) {
          status = "unreadable";
        } else {
          compared += 1;
          const lb = ld.split(" ");
          const rb = rd.split(" ");
          const length = Math.max(lb.length, rb.length);
          let differs = false;
          for (let i = 0; i < length; i += 1) {
            const a = lb[i] ?? "··";
            const b = rb[i] ?? "··";
            const diff = a !== b;
            if (diff) differs = true;
            bytes.push({ l: a, r: b, diff });
          }
          status = differs ? "changed" : "same";
          if (differs) changed += 1;
        }
        if (!sectors.has(sector)) sectors.set(sector, []);
        sectors.get(sector).push({ block: number, kind, left: ld, right: rd, status, bytes });
      }
      this.diffResult = {
        sectors: [...sectors.entries()].sort((a, b) => a[0] - b[0]).map(([sector, blocks]) => ({
          sector,
          blocks,
          changed: blocks.some((block) => block.status === "changed"),
        })),
        changed,
        compared,
        uidDiffers: (this.leftCard.uid || "") !== (this.rightCard.uid || ""),
      };
    },

    visibleSectors() {
      if (!this.diffResult) return [];
      return this.diffResult.sectors.filter((sector) =>
        this.showEqual || sector.blocks.some((block) => block.status !== "same"));
    },

    visibleBlocks(sector) {
      return this.showEqual ? sector.blocks : sector.blocks.filter((block) => block.status !== "same");
    },

    writePayload() {
      return {
        mode: this.writeMode,
        text: this.writeText,
        hex: this.writeHex,
        start_block: Number(this.writeStart) || 0,
        keys: this.parseKeyText(this.writeKeys),
      };
    },

    async previewWrite() {
      this.writeError = "";
      this.writeResults = null;
      this.writeConfirm = false;
      try {
        const body = await this.requestJson("/api/write", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ...this.writePayload(), dry_run: true }),
        });
        this.writePlan = body.plan;
      } catch (error) {
        this.writePlan = null;
        this.writeError = error.message;
      }
    },

    async doWrite() {
      this.writeError = "";
      this.writing = true;
      try {
        this.writeResults = await this.requestJson("/api/write", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ...this.writePayload(), dry_run: false }),
        });
        this.writePlan = null;
        this.writeConfirm = false;
      } catch (error) {
        this.writeError = error.message;
      } finally {
        this.writing = false;
      }
    },
  };
}
