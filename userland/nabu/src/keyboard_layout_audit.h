#import <Foundation/Foundation.h>

/* Call once from the process main thread after linking UIKit. An application
 * or a standalone executable can call it; UIApplicationMain is not required.
 * YES means JSON was written. Inspect nabu_screen_geometry_observed,
 * all_nabu_query_dimensions_positive and the rule-exercise rows for findings.
 * No input-mode preferences or UIScreen methods are changed.
 */
BOOL nabuKeyboardLayoutAudit(NSString *outputPath);
