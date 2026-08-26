import { Container, getContainer } from "@cloudflare/containers";

export class HostingContainer extends Container {
  defaultPort = 8080;
  sleepAfter = "24h";
  enableInternet = true;

  onStart() {
    console.log("Hosting control container started");
  }

  onStop() {
    console.log("Hosting control container stopped");
  }

  onError(error) {
    console.error("Hosting control container error", error);
  }
}

export default {
  async fetch(request, env) {
    const container = getContainer(env.HOSTING_CONTAINER, "control");
    return container.fetch(request);
  },
};
