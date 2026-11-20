/**
 * Camoufox as camoucore sees it: its name, cache directory and environment
 * variable prefix (CAMOUFOX_*), on the Firefox engine.
 *
 * TypeScript twin of python/src/camoufox/product.py.
 */
import { FIREFOX, Product } from "camoucore/product.js";

export const PRODUCT = new Product("camoufox", "Camoufox", FIREFOX);
