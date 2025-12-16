import { MongoClient, Collection, Db, ObjectId } from "mongodb";

/**
 * Shared MongoDB client with global caching for Next.js hot-reload.
 */
let client: MongoClient | null = null;
let clientPromise: Promise<MongoClient> | null = null;

async function getClient(): Promise<MongoClient> {
  const uri = process.env.MONGO_URI;
  if (!uri) {
    throw new Error("Missing MONGO_URI environment variable");
  }
  if (client) return client;
  if (!clientPromise) {
    clientPromise = MongoClient.connect(uri, {
      // Add any driver options here if needed
    }).then((c) => {
      client = c;
      return c;
    });
  }
  return clientPromise;
}

export async function getDb(): Promise<Db> {
  const c = await getClient();
  const dbName = process.env.MONGO_DB || "TheFollowup";
  return c.db(dbName);
}

export interface BronzeLink {
  _id?: ObjectId;
  title: string;
  date: Date | string;
  inserted_at?: Date | string;
  link: string;
  tags?: string[];
  raw_content?: string;
  process_posturing?: boolean;
}

export async function getBronzeCollection(): Promise<Collection<BronzeLink>> {
  const db = await getDb();
  return db.collection<BronzeLink>("bronze_links");
}
