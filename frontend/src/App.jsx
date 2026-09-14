import "./App.css";

import { useEffect, useState } from "react";

function App() {
  const [destination, setDestination] = useState("aws");
  const [inventory, setInventory] = useState(null);

  useEffect(() => {
    fetch("http://localhost:8001/inventory")
      .then((response) => {
        if (!response.ok) {
          throw new Error(`Inventory request failed: ${response.status}`);
        }

        return response.json();
      })
      .then((data) => {
        setInventory(data);
      })
      .catch((error) => {
        console.error(error);
      });
  }, []);

  return (
    <div className="app">

      <header className="header">
        <div>
          <h1>CloudMove</h1>
          <p>
            Selective migration from On-Premise to AWS / GCP
          </p>
        </div>

        <div className="status">
          <span className="status-dot"></span>
          MVP
        </div>
      </header>

      <main className="container">

        <section className="card">
          <h2>1. Source Architecture</h2>

          {inventory && (
            <p>
              Resources discovered:
              <strong> {inventory.resources?.length ?? 0}</strong>
            </p>
          )}

          <div className="source-box">
            <h3>On-Premise</h3>

            <div className="architecture">

              <div className="resource backend">
                <strong>Backend</strong>
                <span>Compute</span>
              </div>

              <div className="arrow">↓</div>

              <div className="dependencies">

                <div className="resource">
                  <strong>PostgreSQL</strong>
                  <span>Database</span>
                </div>

                <div className="resource">
                  <strong>Redis</strong>
                  <span>Cache</span>
                </div>

              </div>

            </div>
          </div>
        </section>


        <section className="card">
          <h2>2. Select Resources</h2>

          <label className="checkbox">
            <input type="checkbox" defaultChecked />
            Backend
          </label>

          <label className="checkbox">
            <input type="checkbox" defaultChecked />
            Redis
          </label>

          <label className="checkbox">
            <input type="checkbox" />
            PostgreSQL
          </label>

          <button>
            Resolve Dependencies
          </button>
        </section>


        <section className="card">
          <h2>3. Destination Cloud</h2>

          <div className="cloud-options">

            <label
              className={
                destination === "aws"
                  ? "cloud-option selected"
                  : "cloud-option"
              }
            >
              <input
                type="radio"
                name="cloud"
                value="aws"
                checked={destination === "aws"}
                onChange={() => setDestination("aws")}
              />

              <div>
                <strong>AWS</strong>
                <span>EC2 / RDS / ElastiCache</span>
              </div>
            </label>


            <label
              className={
                destination === "gcp"
                  ? "cloud-option selected"
                  : "cloud-option"
              }
            >
              <input
                type="radio"
                name="cloud"
                value="gcp"
                checked={destination === "gcp"}
                onChange={() => setDestination("gcp")}
              />

              <div>
                <strong>GCP</strong>
                <span>
                  Compute Engine / Cloud SQL / Memorystore
                </span>
              </div>
            </label>

          </div>
        </section>


        <section className="card">
          <h2>4. Generate Infrastructure</h2>

          <div className="result">

            <p>
              Destination:
              <strong>
                {destination === "aws" ? " AWS" : " GCP"}
              </strong>
            </p>

            <p>
              IaC:
              <strong> Terraform</strong>
            </p>

            <button className="primary">
              Generate Terraform
            </button>

          </div>
        </section>

      </main>

    </div>
  );
}

export default App;
