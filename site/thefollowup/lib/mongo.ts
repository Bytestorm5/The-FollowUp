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
  slug?: string;
  date: Date | string;
  inserted_at?: Date | string;
  link: string;
  tags?: string[];
  raw_content?: string;
  process_posturing?: boolean;
  clean_markdown?: string | null;
  summary_paragraph?: string | null;
  key_takeaways?: string[] | null;
}

export async function getBronzeCollection(): Promise<Collection<BronzeLink>> {
  const db = await getDb();
  return db.collection<BronzeLink>("bronze_links");
}

export interface SilverClaim {
  _id?: ObjectId;
  slug?: string;
  claim: string;
  verbatim_claim: string;
  type: "goal" | "promise" | "statement";
  completion_condition: string;
  completion_condition_date?: Date | string | null;
  event_date?: Date | string | null;
  article_date: Date | string;
  article_id: string | ObjectId;
  article_link: string;
  date_past: boolean;
  follow_up_worthy?: boolean;
  priority?: "high" | "medium" | "low";
  mechanism?:
    | "direct_action"
    | "directive"
    | "enforcement"
    | "funding"
    | "rulemaking"
    | "litigation"
    | "oversight"
    | "other";
}

export async function getSilverClaimsCollection(): Promise<Collection<SilverClaim>> {
  const db = await getDb();
  return db.collection<SilverClaim>("silver_claims");
}

export { ObjectId };

export interface SilverFollowup {
  _id?: ObjectId;
  claim_id: string | ObjectId;
  claim_text: string;
  follow_up_date: Date | string;
  article_id: string | ObjectId;
  article_link: string;
  model_output?: unknown;
  created_at?: Date | string;
  processed_at?: Date | string | null;
  processed_update_id?: string | ObjectId | null;
}

export async function getSilverFollowupsCollection(): Promise<Collection<SilverFollowup>> {
  const db = await getDb();
  return db.collection<SilverFollowup>("silver_followups");
}

export interface ModelResponseOutput {
  verdict: "complete" | "in_progress" | "failed";
  text?: string | null;
  sources?: string[] | null;
  follow_up_date?: string | Date | null;
}

export interface SilverUpdate {
  _id?: ObjectId;
  claim_id: string | ObjectId;
  claim_text: string;
  article_id: string | ObjectId;
  article_link: string;
  article_date?: Date | string | null;
  model_output: ModelResponseOutput | string;
  verdict: string; // supports legacy and detailed categories
  created_at: Date | string;
}

export async function getSilverUpdatesCollection(): Promise<Collection<SilverUpdate>> {
  const db = await getDb();
  return db.collection<SilverUpdate>("silver_updates");
}
