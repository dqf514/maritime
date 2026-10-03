# Veson Nautical IMOS - Complete FAQ Data

> Extracted from: https://vesonjira.atlassian.net/wiki/spaces/help/pages/351273034/Frequently+Asked+Questions
> Extraction date: 2025-09-16
> Total FAQ entries: 348 across 21 categories

---

## Table of Contents

1. [Administration](#administration) (15 entries)
2. [Analytics](#analytics) (19 entries)
3. [API](#api) (4 entries)
4. [Bunkering](#bunkering) (11 entries)
5. [Chartering](#chartering) (42 entries)
6. [Claims](#claims) (6 entries)
7. [Configuration Flags](#configuration-flags) (6 entries)
8. [Cross-Platform](#cross-platform) (3 entries)
9. [Data Center](#data-center) (15 entries)
10. [Distances](#distances) (7 entries)
11. [Error Messages](#error-messages) (21 entries)
12. [Financials](#financials) (45 entries)
13. [Help Center](#help-center) (4 entries)
14. [Integration](#integration) (10 entries)
15. [Operations](#operations) (63 entries)
16. [Sustainability](#sustainability) (3 entries)
17. [Time Charter](#time-charter) (13 entries)
18. [Trading & Risk](#trading--risk) (14 entries)
19. [Voyage Reporting](#voyage-reporting) (24 entries)
20. [Daylight Saving](#daylight-saving) (1 entry)
21. [Other](#other) (1 entry)

---

## Configuration Flags Reference

The following CFGEnable*/CFG* configuration flags are referenced across FAQ entries:

| Flag Name | Referenced In |
|-----------|--------------|
| CFGEnableVoyageRoles | Operations |
| CFGEnableLatLonOverride | Operations |
| CFGInitialSnapshotTimeSelect | Operations, Financials |
| CFGRemoveIncrementalReversedLinesInFinalFreight | Operations |
| CFGAutoCompleteVoyage | Operations |
| CFGEnableVoyestInitBunkerQueue | Operations |
| CFGPreserveGeneratedCargoes | Operations |
| CFGExcludeTcConsFromBunkerCalcs | Operations |
| CFGLaycanDurationInclusive | Operations |
| CFGCacheVoyPnl | Operations |
| CFGEnableTCEmissionsAllocation | Trading & Risk |
| CFGEnableVCCOAEmissionsAllocation | Trading & Risk |
| CFGLinkPaperTradeQty | Trading & Risk |
| CFGDefaultIncludeCarbonExpInPnl | Chartering |
| CFGVoyapiNoShexFactorOnTurntime | Chartering |
| CFGTciBrokerCommOnEstimate | Chartering |
| CFGDefaultTCOutCargoEmissionsSettlementType | Chartering |
| CFGLockPortNameInBunkerReqs | Bunkering |
| CFGLockCancelledRequirements | Bunkering |
| CFGLockConfirmedRequirements | Bunkering |
| CFGEnableScrubberType | Distances |
| CFGAutoVesselCode | Data Center |
| CFGReportLocale | Analytics |
| CFGDisableItemizedDemOnFinalStatement | Claims |
| CFGEnableExtraFrtRateScaleTable | Configuration Flags |
| CFGIgnoreAccrualOnVoyageDelete | Configuration Flags |
| CFGTCOBunkerAdj | Configuration Flags |
| CFGUseNaturalRounding | Configuration Flags |
| CFGChartererView | Configuration Flags |
| CFGEnableCargoItinSupplierReceiver | Configuration Flags |
| CFGDefVoyNoToTcoBill | Financials |
| CFGDefVoyNoToTciPay | Financials |
| CFGEnableAdhocVoyageJournals | Financials |
| CFGUseInvExchInActual | Financials |
| CFGActEnableGLValidation | Financials |
| CFGAutoGenerateTcComms | Financials |
| CFGPostOffhire | Financials |
| CFGFreightCommBasedOnPaidAmount | Financials |
| CFGAlwaysProrateMonthlyTCRates | Time Charter |
| CFGAssignDefaultCompanyOnVoyage | Error Messages |
| CFGShowPortStatusInItinGrid | Error Messages |
| CFGEnableMultiRoleOnAddressBook | Integration |
| CFGAddBookUniqueRefCode | Integration |
| CFGVoyageNoFormat | Operations |
| CFGUseGlobalVoyageNumbering | Operations |
| CFGLibCrMasthead | Other |
| CFGEnableTCEmissionsAllocation | Trading & Risk |
| CFGCurrenciesWithoutDigitsAfterDecimalSeparator | Error Messages |

---

## Administration

### How can I obtain a copy of the SOC I Type II or SOC 2 Type II report
Please visit https://trust.veson.com/ to request a copy of the latest version of the SOC I Type II or SOC 2 Type II report.

### How can I set someone as a Security Administrator when the current one is unreachable?
It is always best practice to have at least two (2) users assigned with System Administrator permissions. This workflow should only be used when the current security administrator(s) cannot be reached. If your organization finds itself in need of a new Security Admin, follow the steps: Navigate to the Help Center, select Veson Support, file a Licensing Request by providing the following information for the new admin: Name or username, Account email address.

### How do I change a user's Authentication Type?
To change a user's Authentication Type, clients must reach out to Veson Nautical Support for these changes to be made on the administrative side. Please provide: User name, Email address.

### How do I find out how many licenses we have?
Please reach out to your Veson Nautical Account Manager or feel free to submit a ticket through the Help Center.

### How do I purchase additional users for IMOS?
To inquire about adding new users to IMOS, please submit a ticket directly in our Help Center using the License Requests drop-down menu.

### How do I request a schema update?
Sometimes you will need schema updates to activate new features. Schema updates can be requested by IMOS clients or are proactively scheduled by Veson. To request a schema update, create the request through the Help Center via the Product Support option, providing a time slot (specified in UTC). Typically, one hour is adequate, but a two-hour window is requested.

### How do I request that a test database be refreshed with the latest copy of production?
Database refreshes are requested by IMOS clients. On-Premise clients will need to refresh their test database by themselves. To request the database refresh, create the request through the Help Center via the Product Support option. Please expect each database refresh to be completed within a two-hour window.

### How do I set up a new IMOS user after additional licenses have been added?
Once you have been notified that your license change has been completed, your administrator or key user must create the new user directly in your IMOS instance. Follow the instructions for IMOS - Creating a New User.

### How to decode and check the valid to date of a x509 certificate?
The client should provide a zip file (that includes IMOS-Raw.cer file, IMOS-Base64.cer, IMOSFederationMetadata.xml file) or IMOS-Base64.cer file only. Open the file with Notepad++. To check the Valid To date, use: https://certlogik.com/decoder/ Copy and Paste the certificate and click Decode. Check the Valid To date.

### How to Open Encrypted Emails
When our team sends you a sensitive email, it is protected using Microsoft Purview Message Encryption. Outlook 365 Users may be able to double-click the email to open directly. Otherwise: Option 1 - Microsoft Account: Click Read the message, Sign in with Microsoft account. Option 2 - Google Account: Click Sign in with Google. Option 3 - Different Email: Click Sign in with a one-time passcode.

### IMOS - How to create a TEST-ONLY User
As an Admin: 1. Create a user in IMOS Prod with password and set to Authentication only. 2. Create the user in IMOS Test with the access rights and set a password. 3. Please ask the user to log in using the "Test Only" user's email address and password. Authentication-Only users do not use up a license in Production, but they do in Test.

### IMOS - Troubleshooting slow load performance
Standard Tips: Check Internet connectivity. Close some tabs and clear Chrome cache. Use Chrome. Check Task Manager for high CPU/memory usage. For heavy reports: check if propeller is spinning (right-click > inspect), check date range (decrease to one day), refresh browser if blank screen.

### My IMOS session timed out. How do I recover my work?
In most scenarios, IMOS autosaves your work when you navigate between workspaces. For security reasons, if IMOS detects that you have been inactive for 90 minutes, a notification prompts you to refresh your browser without allowing you to save. Refreshing will cause minor data loss of unsaved data in the open workspace.

### What is the Veson Nautical client Password Policy?
All new passwords are required to be a minimum of 12 characters and contain at least one lowercase character, one uppercase character, one digit, and one of the following symbols: ~!@#%&_=;:'<,>-.$^{[(|)]}*+?\\

### Why can't I see my company's test site?
An IMOS user set up with SSO signs in to production first to access test. Common reasons test site doesn't appear: The user is not created in the test environment. There are typos in the user name. The user's email address has unnecessary spaces.

---

## Analytics

### Can I export a report that has quotation marks in the title?
Reports can not export if there are quotation marks in the title. Removing the quotation marks from the title will allow the report to be exported without issue.

### How are Age Days calculated in the Report Designer?
Age Days (with the table path Invoice.OperationsInvoice.AgeDays) are calculated using the formula: Current Date - Due Date = Age Days. If your report shows a large number of negative Age Days, check the Due Date to make sure the month and year values are correct.

### How do I get Bunker Lifting Date in Report Designer?
There are two fields: Opr Date GMT (OprDateGmt field in Data Map) in Bunker Invoice table, and Reference Date Gmt (ReferenceDateGmt field in Data Map) in Voyage Bunker Inventory table. If you want to see only Bunker liftings, filter with "Type = Receive" condition.

### How do I remove duplicate rows in my report?
When creating a report in Report Designer, if you have more than one one-to-many join, you might see multiple rows with similar information. Tips: Aggregate Table - look at columns and see if you can remove any table. Create a custom filter. Use Aggregate method and update Join Type from "Join" to "Join Distinct."

### How should I use the "Apply to Join" Option in the Report Designer?
"Apply to Join" means "Apply the filter only to the joined tables." This filter option can be used for one-to-many joins. It is disabled by default. A sample use case is a report that shows TCOV voyages which do not have freight invoices.

### How to calculate difference between Estimated and Actual TCE?
To show the difference of the TCE in Analytics, create a new calculated field and use the expression: VoyageActPnlBasis.Tce - VoyagePnls.Tce

### How to change the default locale date format of report exports
Exporting the report is defaulted to show MM/DD/YYYY. To change to DD/MM/YYYY, go to Data Center > Settings, enter **CFGReportLocale** in the Flag field and en-GB in the Value field.

### How to obtain a quotient with remainder as decimals when dividing in Report Designer
When performing numerical division with the '/' operator, you will always obtain an integer. To display as a real number: Method 1: Create column reference in the expression. Method 2: Use a formula in the expression.

### How to use the Cargo Emissions table for Cargo Emissions Prorations?
The ETS emissions and cost available on the Carbon Calculator can now be attributed to individual cargoes via the Cargo Emissions Table on Report Designer. Utilizing a filter based on a specific Booking No, VslCode+VoyNo, or Cargo ID, emission and cost for each itinerary line will be prorated. The Cargo Emissions Table is a standalone table and is not joinable.

### How to use "Include description in report" in Analytics
When the contents of the Description field need to be embedded in report output, use the "Include description in report" option in Report Designer. The description is only embedded when the report is generated through "Run" function or through a scheduled task; it is never added when the Export To function is used.

### What DBO should I use to get data?
We recommend that our clients use a supported reporting interface to extract data because raw database schemas are subject to change.

### Where do I find the CO2 data in the Report designer?
In order to view CO2 Emissions data in the Report designer, we recommend using the VoyageLegSummary table, where you can access CO2 Emissions data on a Voyage basis.

### Where to find the Bunker consumed data in Report Designer?
It is recommended to use data from the Voyage Leg Summary table in Report Designer. You may find a breakdown of the voyage bunkers consumed in the Voyage Leg Details table.

### Which data field is responsible for the Loading Rate value found in the Port Details Report for Laytime Calculations?
The Loading Rate value will pull from the Cargo contract itinerary, not the Laytime Calculation screen. The LOADING Rate value pulls from the XML field of <LDOriginalValue/> rather than <TimeAllowed/>.

### Which table in Report Designer can I find Voyage Notes created in the Voyage Manager?
The Voyage Notes added in the Voyage Manager can be found in Report Designer under the Claim Notes table. The table can be accessed by via Claim > Claim Notes.

### Why am I asked to enter my Power BI credentials?
If you are prompted to Enter Power BI Credentials, your Microsoft Power BI account password may have expired. You need to access the Microsoft Power BI desktop using the credentials used in the integration (IMOS - Data Center) and not your personal ones. After resetting your password, enter the new credentials in IMOS Data Center > Settings > ANALYTICS section.

### Why are Net Daily (TCE) values mismatched between the Voyage P&L and Analytics reports?
It is expected that the Voyage Manager P&L grid and Analytics may not match. The Voyage Manager P&L uses a cumulative approach (VoyageStart through selected MonthEnd). Analytics uses a monthly breakdown calculation (selected MonthStart through selected MonthEnd).

### Why are there missing columns in a report despite those columns being added in the Report Designer?
Columns can be marked as 'Hidden' in the Report Designer. Hidden column names are italicized. To surface a hidden column, hover over the field and click the pencil symbol, then uncheck the Hidden checkbox.

### Why is the Last Update GMT field (Table: Cargo) in analytics showing different values than the voyage Revisions?
The "Last Update GMT" column of the Cargo table indicates the date and time when a specific Cargo ID was last saved, not the most recent revision date.

---

## API

### How to get XSD format for all vessel forms?
XSD format is available for standard forms. Those who use custom forms available with Veslink Optimum can also achieve the same by use of API calls. Steps to retrieve XSD format via API: Get form identifier: https://api.veslink.com/v1/forms/DMDS/templates?apiToken={apiToken} Get form in XSD format: https://api.veslink.com/v1/forms/DMDS/xsd?apiToken={apiToken}&formIdentifier={formIdentifier} Note! Please replace the DMDS in the APIs with the company code (Example: SCRP)

### What should I do when receiving generic error when submitting an XML for the API POST v1/forms/submit?
When using the API and running the query POST v1/forms/submit?apiToken={apiToken}&voyageNo={voyageNo}&portCallSeq={portCallSeq}&inTransit={inTransit}&async={async}, users can occasionally receive the below error message: {"successful": false, "response": {"errors": [{"exception": null, "code": "UNKNOWN", "message": "An error has occurred."}]}} To troubleshoot the root cause, it is recommended to obtain copies of successful and failed XMLs, then search for discrepancies using an XML comparison (for example https://extendsclass.com/xml-diff.html). [image]

### Which parameters can I use to filter an API call?
Each API call has certain parameters that can be used to filter an API call (e.g., Vessel Code). To see which parameters an API call uses, in the Veslink Service Documentation, click an API call link. If a given parameter does not exist in reference to the API call that is used (e.g., IMO Number), it means it cannot be used for calling results. If you would like to request more parameters for an API call, share your idea on The Veson Nautical Feature Board.

### Why are my filters not applied when I retrieve my Report Designer report through API?
When you retrieve a Report Designer report through API and expect certain filters to be applied to the results without the use of filter tags in your API call, please ensure that the desired filters have been applied and saved in the Design Mode of the report in your Analytics module. [image] Filters that are applied while not in the Design Mode will not be applied when the report is retrieved through API. [image]

---

## Bunkering

### FAQ - Bunker Requirement - Troubleshooting Locked "Request Status" and "Port" Fields
In the course of the bunkering workflow, users may need to update or change the Request Status or Port on a Bunker Requirement. However, these fields may sometimes appear locked. [image]

**Locked "Port" Field** - Review configuration flag **CFGLockPortNameInBunkerReqs**: When enabled, the user is prevented from changing the port name once a requirement is created and saved with any status.

**Locked "Request Status" Field** - Review these flags:
- **CFGLockCancelledRequirements**: When enabled, prevents changing status once set to Cancelled.
- **CFGLockConfirmedRequirements**: When enabled, prevents changing status back to Preliminary once Confirmed/Pending Approval/Approved.

**Module Rights**: "Edit Operator's Fields on Bunker Requirements" controls Request Status. "Edit Bunker Manager's Fields on Bunker Requirements" controls Port field. [image][image]

### How do I correct a duplicate bunker lifting?
If you sail through a voyage with a duplicate bunker lifting, the Operational quantity shows that the vessel took two times the expected bunkers resulting in double the expected bunker consumption. In order to correct the duplicate bunker lifting you will need to update the Activity Reports for the Fueling Port (F) to delete the duplicate lifting. After you update the Activity Reports, the port consumption in Port Activities will need to be updated to represent the correct departure quantity. [image][image]

### How to change the Initial bunker inventory on a Commenced and a Scheduled voyage
Change the bunker calculation method to TBM on Voyage properties. If the voyage is a consecutive voyage then untick the check box "Consecutive Voyage" before changing the bunker calculation method. Go to Bunkers > Voyage Bunkers > Initial Bunkers. The Initial Bunkers can be configured per price and quantity respectively. Save changes and revert the bunker calculation method to the preferred method. [image][image]

### How to invoice multiple costs for each bunker requirement?
There should only be one lifting per requirement and one bunker invoice. If you are receiving additional costs such as barging and commissions as separate invoices, we suggest that you invoice additional costs as "other expenses."

### Is it possible to map the Port Charges value in a Bunker Invoice to the Port Expenses section rather than the Bunkers section of P&L Expenses?
This is not possible. Every item associated with the Business Rule Source BINV is incorporated into the total cost of bunkers, including the Port Charges field (Code: BPORT). The "Port Charges" for bunker invoices are then lumped into the per-unit cost for fuels on the invoice and then accounted for in the "Actual" column as standard bunker consumption. You should only use BPORT if the bunker port charges also affect the cost of bunkers. If the port charges do not affect the cost of bunkers, then you must create a separate Port Expense invoice.

### Why are Bunkers Missing from the PnL?
If there is an unpriced bunker lifting from the previous voyage, the unpriced bunker lot leads to a value of zero, so it is excluded from the PnL and can cause a variation with the estimated column. If you are attempting to troubleshoot bunkers, a great place to start within the voyage is Bunkers > Bunker Lifting > Bunker Details. [image][image]

### Why Are My Bunker Prices So Low On Consecutive Voyages?
Check to make sure that there are no Duplicate Bunker Liftings for on the Voyages. It is possible for vessels to send in multiple Bunker Lifting Veslink Forms for the same Bunker Lifting. If multiple forms are approved and the calculation method is set to "Average", IMOS will take the average price from those forms and apply it. When Voyages are consecutive, The End Qty and End Price of the previous voyage then become the Initial Qty and Initial Price of the following voyage.

### Why are the bunker values in my Bunker Report incorrect but the voyage end quantity is correct?
One reason why the values can be incorrect in the Bunker Report can be due to the initial bunker not syncing with the voyage. In order to resolve this you must re-sync the initial bunkers by making an adjustment (-1MT) to the bunker type within initial bunkers then save the voyage. Correct the adjustment (+1MT) to the initial amount so that and save the voyage. [image][image]

### Why does a bunker price remain in Voyage Bunkers even after the bunker requirement has been deleted, and how do I remove it?
If a bunker requirement is deleted after the vessel has arrived at the bunkering port, its bunker price will remain under the relevant bunker type(s) in the Voyage Bunkers form. To remove the price: 1) Right-click on the port > Port Activities, enter 1 MT under "Received" column and save. 2) Open Voyage Bunkers, remove the price, close and save. 3) Go back to Port Activities and delete the 1 MT entered. Save. [image][image][image][image][image]

### Why doesn't IMOS recognize bunker received quantity from Veslink Form?
IMOS does not recognize received bunker quantities for At Sea Noon Reports and custom Arrival forms, which have the Received quantity column included. Only In Port Noon Reports and Departure Reports (which are Special (S) and Departure (D) Activity Report types, respectively) will record received bunkers and reflect them as Bunker Liftings in IMOS.

### Why is the total closing bunker inventory price so low?
The total closing bunker inventory price in the Bunker Details Report is calculated from the weighted average price of the various bunker lots. If you notice severe pricing issues, verify the total closing inventory quantity for the bunker lots. Negative bunker quantities at closing could result in a lower total closing inventory price.

---

## Chartering

### Can I delete or unlink a fixture from a scheduled voyage without deleting the voyage?
No. Once a cargo fixture is linked to a voyage, it creates a permanent connection between the cargo and the voyage. This means the fixture cannot be unlinked or deleted independently of the voyage. Additionally, the Opr Type of a voyage can only be changed from TCOV to TCTO if there is no fixture number associated with it. In all other cases, changing the Opr Type or removing the fixture requires deleting both the voyage and the fixture.

### Carbon Calculator 'Include in PnL' by default
**Config Flag: CFGDefaultIncludeCarbonExpInPnl** - We have introduced this flag to default Include In PnL on the Carbon Calculator. Previously, clients would need to create a .TDEFAULT estimate with the box checked, select a random vessel, check 'Include in PnL', save, then remove the vessel and save again. [image]

### Discrepancy Between Net Voyage Days in Fixture and TCO Estimate Explained
When a TC-Out (TCO) estimate is fixed and linked to a voyage, users may notice that the net voyage days in the fixture/voyage are different from the days shown in the estimate. The discrepancy is caused by: The TCO duration in the estimate has been manually amended, AND the estimate is fixed as a Trip TC contract rather than a Period TC contract. Fix: Option A - Fix as Period TC. Option B - Amend voyage itinerary to add idle days. [image][image]

### Error: Voyage could not be loaded after deleting the TC contract the voyage was created from
If you are receiving an error, "Voyage could not be loaded." when trying to open an existing voyage, it could be a result of deleting and updating the time charter contract that the voyage was created from. To avoid the error message, create a new TC for the voyage, which will automatically assign the old TC Code, and after saving the fixture, the voyage can be opened. If the user does not want the voyage linked to the TC, they should remove the TC from the voyage before deleting the TC fixture.

### How are estimated Port days calculated?
The estimated Port days field in the Estimate is calculated using the following formula: EstPD = [(L/D Qty / L/D Rate) + TT] x Terms. The Laytime Terms are defined in the Data Center by Veson and they are measured by a Factor. [image] Depending on the cargo terms, you may need to alter the calculation formula by enabling the Configuration Flag, **CFGVoyapiNoShexFactorOnTurntime**. Doing so will alter the way the estimated port days is calculated: EstPD = ((Cgo Qty / LD rate) x Laytime Term) + TT

### How are Miscellaneous Expenses calculated in Deviation Estimates P&L?
In the Deviation Estimates P&L, the Miscellaneous Expenses line includes the sum of two components: Cargo Expenses and Miscellaneous Expenses. [image] These two categories are combined because, in the current setup, there is no dedicated line item for Cargo Expenses in the Estimate's P&L.

### How are pricing terms selected?
On the Pricing tab of a Cargo, VC In, or COA, the pricing row is selected based on a scoring system: If a pricing row perfectly matches an itinerary (Load Port(s), Discharge Port(s), and Cargoes match), the first such row is used. If a perfect match is not found, scoring considers port matches (+2 for single match, +1 for multiple/unspecified, -10 for mismatch) and cargo matches (+2 for match, +1 for unspecified, -10 for mismatch).

### How can I adjust the commence date of a consecutive Voyage?
When the consecutive voyage checkbox is selected, the current voyage is linked to the previous. [image] This means the initial bunkers, start date/time and some other values are taken from the previous voyage. To amend the start time of a consecutive voyage, you will need to adjust the end time of the previous linked voyage.

### How can I deselect the Intercompany checkbox on a TC Contract?
The Intercompany checkbox is used to link two TC contracts together. [image] This checkbox can only be unchecked if there are no invoices or voyages linked to the respective TCs, otherwise you will receive an error. [image]

### How does Advanced Pricing rules in VC In COA and Cargo contract impact demurrage/despatch rates?
There are several options within the VC In COA and Cargo contract that determine the demurrage/despatch rate. These include: VC In COA Advanced, Advanced Pricing Overrides 'Demurrage/Despatch', Cargo Contract Use Pricing from COA, and Cargo Contract Advanced. [image][image] If Use Pricing from COA checkbox is checked in the cargo contract, the operator will not be able to edit the demurrage/despatch rates manually. The VC In COA's rates will override if both Advanced Pricing Overrides 'Demurrage/Despatch' and Use Pricing from COA are checked.

### How does the system calculate LS Sea Day greater than Total Sea Days in Estimate?
If the LS Sea Days value is greater than the Total Sea Days, please check the weather factor specified in the estimate. The Total Sea Days reflect the actual number of days spent at sea during the voyage, while the LS Sea Days are adjusted based on the weather factor included in the estimate. [image]

### How do I manually change the Bill By field in the Cargo of a mirrored relet voyage?
In a mirrored relet voyage, updates to Cargo contracts across both the operating and relet voyages are usually driven by the Cargo contract on the operating voyage. If the Bill By field is locked, you can manually change it by clicking the value of the CP Qty/Unit field. The CP Quantity Details form appears, on which you can manually change the Bill By field. [image]

### How is Daily Cost determined on the Speed Comparison Analysis form?
On the Speed Comparison Analysis form, Daily Cost is an average of the Hire Rate found on the Time Charter (TC) contract linked to the Estimate. Example: TC In Hire Rate is $4,000 for first 10 days and $10,000 for next 10 days. Average = [($4,000 * 10) + ($10,000 * 10)] / 20 = $7,000/Day. [image][image]

### How Should I Handle a Change in TC Owner When a TC Invoice has Already Been Raised?
Once a Time Charter invoice has been raised, the owner field in the contract will be locked. A single voyage cannot be linked to more than one Time Charter contract. To handle ownership change: Update existing TCI contract by modifying redelivery port, create a new TCI contract under new owner, schedule a new voyage linked to the new TCI. Note: Statement of Account (SoA) is scoped to each contract individually.

### How to make the Laycan period in the Cargo Booking to match the Laycan period in the cargo?
The "Period Basis" field determines how the booking-level laycan will update the laycan(s) of cargoes within the booking. If set to "Default", the booking laycan will be copied as-is. If unset, the total duration is calculated to distribute across cargoes. [image]

### How to troubleshoot error - I/C Company is missing
The Intercompany check box in a Cargo contract enables Contract / Invoice Mirroring functionality. The cause for this error is due the selected company not being an internal company. To resolve this, ensure that for both Counterparty and Company entered in Cargo contract, the Internal checkbox should be enabled in the Address book record. [image]

### If the delete button disappears from a Cargo, what steps should I take to make it return?
If the Delete icon does not appear on a user's screen but can be seen when impersonating the account from Veslink, the specific user must logout > clear the cookies and cache > then log back in. [image] Note: The field may take some time to re-appear.

### Is it possible to create multiple Port/Berth combinations in the Cargo COA itinerary?
It is not possible to create multiple Port/Berth combinations in the Cargo COA itinerary. Instead, create logical berths for the same port to get different L/D rates. For example: QUAY1, QUAY2. Users would treat these as the "same" berth, but logging them as unique so that multiple PORT+QUAYX line items can be created.

### Is it possible to uncancel a Cargo?
In IMOS, a user could accidentally set the status of a cargo card to cancelled. This permanently locks the card and prevents any status update. If a user intends to fix the cargo, they will need to either copy the existing cargo or create a new cargo.

### Is it possible to uncancel a Fixture?
Yes - In IMOS On-Prem and IMOS, Fixtures can be canceled if any details are incorrect or missing. Canceling a Fixture will lock the record. However, users will be able to Uncancel a fixture if the user has the 'Uncancel a Voyage Fixture' permission enabled. [image]

### On a TC In, how can I add a Broker at a different "From GMT", while keeping the first Broker?
In order to add a Broker that starts at a separate "From GMT" from the first/original Broker, you must add the new broker twice. First insert new row with the new broker, the rate set to 0, and input the wanted From GMT. Next insert another row, with the same broker, and the wanted rate. [image][image]

### What is the firmed CP Qty field?
The firming qty field was added to capture information from pre-fixture negotiations. The firmed CP Qty field is read-only. The value in the CP Qty field is captured and stored when the voyage is set to the status "Scheduled." [image]

### Why am I getting the message "Save error - unable to update voyages linked to cargo" when saving a cargo?
[image] This error occurs when: The Voyage linked to this Cargo is in Completed status, AND There is at least one M-port in this voyage, but not every load/discharge line is linked to an M-port. Ensure that there is an M-port for every L/D line in the itinerary.

### Why am I not allowed to adjust the Time Charter Bill date?
One reason is due to the previous Time Charter Bill Date ending later than the current Time Charter Bill Date. [image] To make an adjustment you have to reverse the previous time charter bill transaction. [image]

### Why am I receiving "ERROR" - The TCO Delivery Port should only be specified on the first voyage for TC Out?
[image] This error can occur if the voyage's TCO code is mistakenly entered in another voyage. You must check other voyages for the same TCO code, once identifying the error enter the correct TCO code.

### Why are Hire Adjustment items not included in the Hire Statement?
Hire Adjustment items in a Time Charter invoice (bill code HIADJ) are not included in the Hire Statement as they are typically used for unsettled items, for example an unsettled off hire that the counterparty has deducted from an invoice.

### Why are there two Payment Terms in a cargo contract?
Each Cargo contract has two separate Payment Terms. These correspond to the Laytime Calculation and Freight Invoice of this cargo. Invoice % specifies the default invoicing percentage. If not specified, IMOS uses **CFGFrtinvPercent** for Invoice %. [image]

### Why Are Tolls Categorized as Port Expenses in Deviation Estimates?
In Deviation Estimates, tolls are categorized as port expenses. This approach is a design choice made to simplify the Deviation Estimate P&L and streamline the calculation process. [image]

### Why does my itinerary have duplicate passing points?
Duplicate passing points may appear due to Fuel Zones updates in the Data Center. When new Fuel Zones are enabled, the old ones remain for historical reasons. Fuel Zones updates are regulated by deactivating older versions to avoid duplicate passing points.

### Why doesn't the column view of a user defined field automatically update when amended in the Data Center?
Changing the name of a UDF in the Data Center is not expected to update the respective column name in the list view. This is by design as column names are saved as part of list views. You may inactivate a UDF and then add a new one versus changing the name of an existing field. [image][image]

### Why does the Laycan Range value of a Cargo/VC In as viewed from the Cargo/VC In List differ from the laycan window indicated in the contract itself?
The Laycan Range figure seen in the Cargo/VC In List is in GMT, whereas the Laycan From/Laycan To values indicated in a Cargo/VC In contract is in the time zone of the first load port. [image][image]

### Why do I have idle days in my TCO estimate?
The "Idle" column indicates the number of days a vessel remains in port without engaging in any port activity. Idle days may appear at the port immediately before the TCO redelivery port to ensure total voyage duration matches the planned TCO duration. If you prefer automatic calculation, enable the "Trip TC" option in the estimate properties. [image]

### Why don't I see any regions in the "Regions" section in Market Insights?
To be able to view/retrieve regions, you should first create your own regions using the polygon tool. Regions are not pre-populated.

### Why is bunker cost calculated in the TCTO Estimate?
In IMOS, if the TCTO estimates indicate bunker costs, verify the itinerary sequence of the estimate. The port itinerary sequence must align with the TCI Contract. Once the delivery port is designated as the first port, bunker expenses will be automatically excluded.

### Why is my address commission not imported from my TC In into my Estimate?
If the address commission rate did not flow into the Estimate, make sure the voyage duration of your Estimate is greater than zero. When voyage duration is zero, address commission is not yet imported. [image][image]

### Why is my TC broker commission not reflected in the Voyage Estimate P&L?
**Config Flag: CFGTciBrokerCommOnEstimate** - Enable this flag. Once enabled, a new field Hire Comm (%) will be available in the voyage estimate. [image]

### Why isn't the emission rebill showing on the Estimate column?
**Config Flag: CFGDefaultTCOutCargoEmissionsSettlementType** - This is almost always caused by this flag being set to N/A. When N/A, the system suppresses the rebill from the Estimate column. If changed to any non-N/A value, the rebill will appear. [image][image]

### Why is the Bareboat Off-Hire amount not reflecting correctly in the voyage P&L?
The discrepancy is typically caused by a currency mismatch between the currency of the Bareboat contract and the currency used in the Miscellaneous Off-Hire entry. [image] Ensure both are using the same currency.

### Why is the Demurrage/Despatch missing in the Estimate PnL?
Demurrage or Despatch requires two fields to be populated: the rates per day and the number of Demurrage/Despatch days. These are entered inside the port itinerary details. [image][image]

### Why is the Estimate ID Not Auto-Generated When Creating a New Estimate?
The maximum limit of characters for the EstimateID has been reached. The system's limit is 9 alphanumerical values (user initials + estimate number, e.g. ADMIN-9999). Solution: Shorten the user's initials (e.g. ADMIN -> ADM), then log out and back in.

### Why is there a difference between TCO Duration and Net Voyage Days in the Estimates?
The TCO Duration is derived from the TCI contract, while the Net Voyage Days are calculated based on the itinerary (Sea Days + Port Days). The TCO Duration field is a text field, allowing manual entry.

### Why is the TCI Bunker Adjustment not displayed in my Voyage Estimate?
Three things must be true: 1) TC In contract code is linked to the estimate. [image] 2) "Last TCI Voy" is ticked in the estimate's Properties panel. [image] 3) The TCI contract has a Projected Redelivery quantity entered. If the projected End ROB for a bunker grade is negative, IMOS suppresses the adjustment line entirely.

---

## Claims

### Can I have two separate brokerage commission lines for the same Broker?
This is possible for Freight Invoices as both lines will generate a brokerage commission each. However, for Demurrage Invoice, adding the same broker twice (e.g., Broker A 3.75% and Broker A 1.25%) is not supported. Options: Aggregate the two into one single entry, or create a "dummy" broker for the additional percentage.

### How to prevent linked Demurrage/Despatch costs from aggregating on a Freight Invoice
**Config Flag: CFGDisableItemizedDemOnFinalStatement** - Set to 'N' to prevent aggregation. If items still aggregate, delete the afflicted line item, create a new Laytime Calculation, and re-add via "Add Details".

### Why am I getting the program message, "Error in update: Table task has been updated since last read, record cannot be saved."
This error typically occurs when multiple users are making updates simultaneously. Use only one IMOS tab when making updates. Refresh and save the page before proceeding with any changes.

### Why do the fields Total Demurrage Time, Demurrage Days, and Demurrage rate not show on the Laytime Calculation Report?
These fields are linked to the different Laytime Calculation methods. If the Calculation method is 'Standard' these fields will not show. If the Calculation method is 'Reversible' these fields will show.

### Why is the broker commission on a demurrage invoice being calculated on net demurrage instead of total demurrage?
If the demurrage and despatch are together, IMOS calculates as demurrage less despatch. To avoid this, create one laytime claim for despatch and another for demurrage. On the demurrage calculation's claim tab, check the address commission included; on the despatch calculation, do not select the check box.

### Why port activities are not imported into laytime calculation?
Check if a specific port activity is marked as the one to be imported into laytime calculation. Go to Data Center > Port Activities > make sure Laytime Calc Import is ticked. [image] For activities like Start Loading or Discharging cargo, check if they are linked with the cargo in the BL Info tab. [image]

---

## Configuration Flags

### CFGChartererView
Name: Charterer View. Description: Controls charterer view settings.

### CFGEnableCargoItinSupplierReceiver
Name: Enable Cargo Itinerary Supplier Receiver. Description: Controls cargo itinerary supplier/receiver functionality.

### CFGEnableExtraFrtRateScaleTable
[image] Requires this flag to be enabled. In the Cargo/COA Contract's Extra Freight Terms grid, when a scale table value is populated, the right-click dropdown menu displays "Choose Scale Table" and "Edit Scale Table" options. [image]

### CFGIgnoreAccrualOnVoyageDelete
Name: Ignore Accrual on Voyage Delete. Use Case: When accruals are set to always prorate and voyages with P&L actuals are scheduled in advance. Enable this flag to bypass the error when adjusting vessel/voyage details on a voyage with an accrual. [image] Alternatively, rerun accruals on a recalculation basis, reject pending records, then delete/adjust the voyage.

### CFGTCOBunkerAdj
Name: TCO Bunker Adjustment. Default: N (disabled). When enabled (Y), the gain/loss from delivery and redelivery bunkers are recorded. When generating Voyage Period Journals, there will be an extra journal, TCO Bunker Adjustment. The calculated price difference can be linked to a P&L-affecting account (expense account).

### CFGUseNaturalRounding
Name: Use Natural Rounding. Alternative method for invoice rounding. Binary floating-point arithmetic can cause one-cent differences. Enabling this flag uses an alternative rounding method. Notes: Will not affect posted invoices. May need to click Custom Flag button to find this flag.

---

## Cross-Platform

### How do I allow access to the Veson Platform in IMOS?
All IMOS clients now have access to the Veson Platform. For a Specific User: Navigate to IMOS > Data Center > Security > user profile > Select "Allow Veson Platform Access" and Save. [image] For All Users: IMOS > Settings > Grid icon > Configuration Flag List > Select "Allow Veson Platform Access" under Veslink Site Info. [image][image] Access at app.veson.com with existing IMOS credentials.

### How do I chat with CoCaptain?
CoCaptain is Veson's AI assistant, part of the Veson Platform. Go to app.veson.com and sign in with existing IMOS credentials. CoCaptain pulls in specifics of voyages, cargoes, and counterparties directly from IMOS. Fin (in current IMOS) helps with everyday "how do I" questions. CoCaptain goes further with detailed analysis. CoCaptain is included at no additional cost for current IMOS clients.

### What is the Vessel Insights field in IMOS?
This field is for Veson Platform users who use Vessel Insights. It's a new column in Data Center > Vessels > Fuel/Lube Types table that maps a Vessel Insights fuel type (HFO, LFO, or MDO) to a corresponding IMOS fuel type. If you don't use Vessel Insights, leave it unmapped - it has no effect on existing workflows.

---

## Data Center

### Can I turn Fuel Zones on/off?
Fuel Zones cannot be turned off once they are in use. To inactivate a Fuel Zone so that it cannot be used in new Estimates and Voyages, select its Inactive check box.

### How can I automatically generate Vessel Code upon vessel creation?
Enter a custom expression as the value of configuration flag **CFGAutoVesselCode**. Use [A-Z] for letters and [0-9] for numbers. Example: Vessel Codes will start with A000 and end with Z999. [image] You can also set fixed characters (e.g., Z9[0-9][0-9] generates Z900-Z999).

### How can I set up a Task & Alert rule for Vars-related fields?
In order to set up a condition for vars-related fields like Constants Sea, Constants Lakes, Fresh Water, or Others, ensure to pick them up from the Vessel Variables table in the Task and Alerts. [image][image][image]

### How can I set up a Task & Alert rule set involving both "And" and "Or" operators?
Conditions B and C must be in a group, separate from condition A. [image] To add a group, click the menu next to the condition and select "Add Group". [image]

### How do I set up recurrence options for scheduled tasks?
Veson Support can set up recurring scheduled tasks: By time intervals in minutes, at a specific time daily, or at a specific day and time. Support can only use one pattern at a time. For multiple days, create duplicated tasks.

### Is there a security right that prevents users from creating new vessels?
There is no access right that prevents users from creating new vessels while still allowing editing of existing vessels. The 'Vessel' and 'Vessel List' options under Data Center > Quick Links provide standard rights only.

### On Fuel Zones, why doesn't (cons rate only) compound onto the low-sulfur fuel?
On the Fuel Zones form, only one low-sulfur fuel can be selected to consume in an ECA Zone when a (cons rate only) fuel is selected. Confirm that the ECA Worldwide Zone is only configured with one low-sulfur fuel.

### System warning when no consumption line matches the vessel
IMOS may prompt a warning when updating speed lines in the Speed Consumption Table. The warning depends on Ownership type - triggers only for OV and TC Ownership. [image] Note: Speed Laden and Speed Ballast fields are not automatically updated when rows are added/removed from the Speed Consumption Table. Always verify manually.

### What is the impact of changing the Delay Property field?
The property field in Delay Reasons is used only for reporting purposes. It does not impact the Voyage P&L or an Estimate. Changing to Planned Maintenance enables off-hire reporting in the On/Off Hire Summary. [image]

### Why am I unable to add an Attachment on the Time Charter Task screen?
Attachments on the Time Charter Task screen are associated with the Rule, not the Task instance. To add Attachments, right-click the Task result at the bottom of the Task & Alert Rule Form, select 'Attachments'. [image][image][image][image]

### Why am I unable to see the full list of logs in the Interface Message List in IMOS?
IMOS loads a preview set of data for large datasets. When you see "To minimize load time, a list preview appears", narrow your search by applying filters with a specific date/time range or filters marked with the orange triangle. [image] This behavior applies to all List views in IMOS.

### Why can't I export lists or reports to PDF?
Check browser settings to ensure PDFs will download. In Chrome, make sure PDF files download instead of automatically opening in your browser. [image]

### Why does the Revisions panel show changes that users did not make?
The Revisions panel displays a chronological list of revisions. Multiple changes may be logged if data points are related (e.g., changing Speed forces update of Estimated Arrival/Departure values). Reach out to Veson Support through the Help Center for further explanation.

### Why do I see the error message "An error occurred while deleting the record. The O-Type record has been used and cannot be deleted." when trying to delete an Address Type?
This occurs when the Address Type has been used in an invoice at any point. Once an invoice is created, the system permanently retains its association. Set the existing record to Inactive and create a new record with the correct Type. [image]

### Why is the drop-down list for a data field highlighting the top result and not the selected value?
Clicking the dropdown arrow shows the field autocomplete based on the current text value and will yield the top result, not the selected result. This is by design.

---

## Distances

### Do I need to run the UpdatePortsNoUNCodes script found in Distances releases?
The "updatePortsNoUNCodes" script is the same as "updatePortsV7" but will not update UN codes. Some clients add their own UN codes and want them to remain unchanged. You can ignore this script if you don't add or use your own UN Codes.

### How can I retrieve the VesID of a standard port?
Two methods: 1) Navigate to https://www.veslink.com/distances/distancerouteservice.asmx > GetPortByName. [image] 2) Build a Report Designer report including the Ports data table; VesID is under the Veson ID column. [image]

### How do I add a new Standard Port to the Port list and Distances?
Submit a case to Veson Support with: Port Name, Country, Latitude, Longitude, GMT Offset, UN Code, Scrubbers Allowed (Open/Closed/Not Allowed). Submit LAT/LONG in degree-minute-second format, not decimal.

### IMOS - ECA Bohai Sea Scrubber Restriction
As of March 2026, a new ECA fuel zone: ECA - BOHAI SEA - SCRUBBER RESTRICTION. [image] This zone prohibits scrubber use within the Bohai Sea. The zone works alongside ECA - CHINA with the most specific zone taking precedence. Closed Loop scrubbers: permitted. Open Loop: not permitted (switches to Non-Scrubber tab). No Scrubber: standard low-sulfur consumption. Setup requires **CFGEnableScrubberType** to be enabled.

### Why are the miles between ports incorrect?
The issue is due to incorrect miles entered within the Observed Distance column in the Activity Report of the previous port. [image] As Veslink forms get approved, values in the Observed Distance field will update accordingly. The Observed Distance field is found in Noon Reports and Arrival Notice. [image][image]

### Why does my Itinerary show zero miles?
This typically occurs when a region has been included on the Itinerary and the previous Port is within that region. There is no distance to travel between that Port and region as they are in the same location. [image]

### Why is there a difference in the miles calculation between IMOS and Veslink?
Veslink Distances does not always have the same routing preferences as the IMOS Estimator. IMOS takes into account the client's settings, while Veslink uses a more general set of inputs. The comparison between the two systems is not like-for-like.

---

## Error Messages

### ALERT ERROR
[image] A pop-up message containing ALERT is set up in the Task & Alert Rule Set List and can prevent saving. If the Alert is not correct, set it to inactive and reexamine conditions. Always test new Task & Alert Rule setups in test environment first.

### An error was encountered while retrieving data. If this problem persists, please contact Veson Support.
Common error in the Agent Portal workspace. Often caused by the Messaging Service being offline. Resolve by: On-Premise/IMOSlive clients restarting their Messaging Service; IMOS clients reaching out to Veson Support.

### Cannot insert duplicate key row in object '[table]' with unique index '[index]'
[image] Delete any attachments from the invoice in order to address this error when attempting to reverse invoices.

### Cannot insert duplicate key row in object 'dbo.invoice' with unique index 'invoice_index01.'
When posting an invoice, this error means more than one user is attempting to post the same invoice at the same time. [image]

### Cannot insert duplicate key row in object 'dbo.tradecontr' with unique index 'tradecontr_index01'
Impacts Trading P&L Snapshots. Often caused by two "current" voyage snapshots for a problematic cargo. Open and re-save the voyage to remove the duplicate snapshot.

### Cannot modify counterparty
When changing counterparty to a cargo contract: "A freight Invoice has been created for this cargo and its counterparty cannot be changed." [image][image] Navigate to the Voyage, find the Invoice, Reverse it, then change the counterparty. [image][image][image]

### Failed to execute query to update vsched XFIX
Unable to delete a scheduled voyage. Identify the Port Call and delete the port (may add an additional port leg). [image]

### Failed to launch oprbill.exe error
[image] Result of IMOS Shell not being able to access child executables. Check that the Start in value of the desktop shortcut is set to the directory where IMOS \exe* files are stored.

### Failed to update bill record
On rare occasions, bad data can be generated against the Operational side of an invoice. [image] Reject the invoice, delete the "Pending" invoice, create it again, then Approve and Post.

### Field_UserField_<number> not found in <table> table
When making the v1/imos/reports/ API call, this means a new User-Defined Field has been added. Submit a Support request to restart the messaging service.

### How to Troubleshoot a Cargo Import
Common issues: Invalid port data in the itinerary. Review port information within the XML and ensure they match the information under Data Center > Port.

### How to Troubleshoot System.Runtime.InteropServices.SEHException (0x80004005)
For On-Premise clients: Housekeep unused files in imos/dat and imos/db. Ensure only one version of vesonx70.dtx in imos/dat. Ensure only two versions of updatePortsV7.sql and tzoneUpdate.sql from the same Distance release.

### Line 1 Company Code is Blank
When importing PDA/FDA items via XML, Company Code is missing. Check <invoiceDetailsLine> section for <companyCode> tag. Can be alleviated by enabling **CFGAssignDefaultCompanyOnVoyage**.

### Total Owner's quantity should not exceed Total Redelivery quantity
On a TCTO Voyage, the lifted bunker quantity on the owner's account is higher than the actual redelivered amount. [image] Check that redelivery bunker quantity is higher than or equal to the sum of all bunkers lifted on the owner's account. Split quantities on bunker liftings if needed.

### Transformation file report2rdl.xsl is not found
When running Scheduled Tasks, ensure that the working directory field in the configuration is left blank. [image]

### Veslink Error | Oops! Something went wrong while processing your request
Troubleshoot: Log out and back in. Clear browser cache. Check if the vessel has been properly activated for Voyage Reporting.

### Veslink Onboard - User Master.Smith is external only and may not log on interactively.
[image] Result of validation for users set up with External Access Only. Ensure user is ticked with External Access Only, has access to specific vessel in Object Rights, and has Operations > General and Operations > Actions > Onboard rights. Refresh database with "Bulk Import".

### Voyage Reporting - Form Processing Errors
Comprehensive list of form processing error messages including: permission errors, missing JSON parameters, form template issues, transaction validation failures (missing report type/time/ROBs), port activity errors, bunker ROB errors, cargo errors, and many more. Key errors include: "Cannot modify redelivery at {port}" (triggered by **CFGShowPortStatusInItinGrid**), ROB discrepancy errors, currency errors (related to **CFGCurrenciesWithoutDigitsAfterDecimalSeparator**), and various submission order validations.

### What do I do if I see the error message "Inquiry external reference is already in use" when trying to save a Bunker Requirement?
[image] This occurs when information is interfaced from an external source with an external reference. [image] Remove the external reference, change the bunkering port, then re-enter the external reference.

### Why am I receiving "System.OutOfMemoryException" errors when loading lists in my database?
Result of too much stress on the database. Filter large lists to alleviate stress. Monitor RAM usage when loading reports or voyages with many ports.

### Why does a payment batch fail with the error "finished with exit code -104"?
May be due to: XML referencing a date in the future, or invoices in the batch having incorrect Transaction Data Entry status (Canceled instead of Posted).

---

## Financials

### Can Port Disbursement adjustments be hidden from the Actual column in the Voyage P&L?
No. PDA/FDA exchange rate mismatches produce adjustment items that appear in both the FDA invoice and the Actual column. Both IMOS On-Prem and IMOS recognize the port expense at the FDA exchange rate. This behavior is hardcoded and cannot be modified.

### Difference between Non-Voyage Journals and Ad-Hoc Journals
**Non-Voyage Journals**: Transfer between Balance Sheet accounts only. Should not be linked to any voyage. Must not involve P&L accounts. **Ad-Hoc Journals**: Transfer from Balance Sheet to P&L account. Requires **CFGEnableAdhocVoyageJournals** flag. P&L line should be linked to a voyage; Balance Sheet line should not.

### Error Line 1 Ledger Code is blank - Error creating I/C Journal for payment
When an invoice has a Payment Company that is intercompany, an intercompany journal is created. The Line 1 Ledger Code cannot be filled if the Account Periods form does not have an Intercompany ledger code entered for the year specified.

### FAQ - TC-In or TCO Bill Line Items Not Appearing in Voyage After Posting
Verify whether the voyage number is specified for the line item. [image] Solution: Reverse the invoice and select the voyage number. Enable **CFGDefVoyNoToTcoBill** and **CFGDefVoyNoToTciPay** to auto-populate voyage numbers. [image] For mirrored invoices, amendments must be made within the originating contract. [image][image]

### How are EU ETS Costs and FuelEU Costs Calculated When Apply Carbon Expenses to Period is Enabled?
[image] Formula: Actual Fuel Consumption * Phase-In % * ETS % * CO2 Factor / Currency Exchange Rate * CO2 Price per MT. Uses actual bunker consumption from noon reports rather than estimates.

### How are the date values in the Final Freight Statement populated?
Invoice Date defaults to the creation day. Due Date defaults to 15 days afterward. Both can be changed. [image]

### How are the Provisional Port Expenses used?
When actual costs >= estimated amount, system shows total final cost. When actual < estimated, the system shows actual port expenses plus the remaining estimated amount as Provisional Port Expenses. [image][image][image] Requires "Use Estimate Cost on P&L" to be checked. [image]

### How does <externalRefID> field in simplePayment XML file affect payments in IMOS?
Maps to Reference No. field on Transaction Data Entry form. A user will override a previous payment when importing with the same externalRefID. Unique reference IDs are required. Multiple payments possible when externalRefID differs for each.

### How Do I Create a Freight Invoice Based on Separate B/L Quantities for One Cargo?
Step 1: Set 'Bill By' to B/L Quantity in CP Terms Details. [image] Step 2: Configure Pricing with Top Off set to Regular. [image] Step 3: Enter B/L Quantities in B/L Info section. [image] The freight invoice will include separate rows for each B/L quantity.

### How do I create Freight Invoices for a Voyage with multiple Cargoes of the same Counterparty?
Two methods: 1) Create one Freight Invoice with all cargoes - system brings all cargoes of the Counterparty. [image][image][image][image] 2) Create one Freight Invoice for each Cargo individually. [image][image][image]

### How do I export an invoice as an XML file?
Navigate to any invoice > View Operations Invoice or View Financials > hold CTRL key and select the PDF button. [image][image][image][image][image] A new tab will appear with the XML.

### How do I troubleshoot bunker variances for Model B setup?
Model A: Invoices are prepayments suspended in balance sheet. Model B: Invoices are expenses immediately posted in P&L. Model B requires more meticulous voyage/month-end closure to avoid variances.

### How many decimal places are used in the Veson IMOS Platform's back-end calculations?
IMOS displays up to 6 decimal places and utilizes decimal values of up to 15 total characters. Hover over a field to see the fully stored value. Exception: when 0 is the only integer before decimal, 15 characters after decimal are displayed. [image][image]

### How to amend the Amt From/To at the Invoice Approvals Restrictions screen
Navigate to Financials > Financial Control, find the relevant Invoice Type, increase the limit next to the relevant User Group and Save. [image][image]

### How to delete unneeded APRs from PDA
Step 1: Open Port Expenses, select "Hide lines with zero amount". [image] Step 2: Click PDA/APR tab. [image] Step 3: Delete all values in Column 2. [image] Step 4: Delete all values in the bottom table. If a line is yellow, right-click > see details > delete values in "APR". [image]

### How to handle incorrect account type mapping in Business Rules
If a code is incorrectly mapped (e.g., Balance Sheet instead of P&L), amounts may be missing from or appearing incorrectly in the Posted column. Resolution: Create correct account in Chart of Accounts, update Business Rule, reverse and repost all affected invoices.

### How to remove Estimated Bunker expenses from the Voyage P&L for consumption estimations that do not exist in the linked Estimate
Likely due to **CFGInitialSnapshotTimeSelect** being set to "Commence". Navigate to voyage P&L > Snapshot dropdown > "Update Initial Snapshot" > Save.

### How to resolve "Invoice Currency is Missing" error during payment
The company's remittance details in the Address Book do not include a valid currency. [image][image] Open the company's record > Select correct CURR > Save. [image]

### IMOS - Can IMOS Handle Currencies other than USD as Base Currency?
YES. The base currency can be indicated as any currency (e.g., JPY). Default reports show everything in BASE CURRENCY. [image][image][image][image] **CFGUseInvExchInActual** uses the exchange rate specific at the invoice level.

### In the Voyage Invoice List, how do I delete Create Freight Invoice items from old Cargo contracts?
Create a new Cargo COA using the original Charterer name, assign Cargo contracts to it, open CP Terms Details and click Update Fixture, then save Cargo, COA, and Voyage in sequence.

### Unable to delete Monthly Accruals due to "Only non-voyage related transactions can be deleted" error
IMOS does not allow deletion of accrual journals as they are voyage-related transactions. To correct, recreate the accrual journals for the relevant period, which will override incorrect data. [image]

### What could happen if my PDA currencies do not match up with my FDA currencies?
Mismatched currencies between PDA and FDA can cause posting errors after PDA adjustments due to VIP's inherent rounding logic. [image]

### What does "DRAFT" watermark in the invoice mean?
Indicates the invoice has been generated but not yet posted. Invoices with "READY TO POST" status still show the DRAFT watermark as details remain editable until officially posted. [image]

### What does it mean when an accrual line is red?
An accrual line may appear red if Business Rules are not properly mapped or there is a P&L invariance. Check the Bill Viewer, Voyage P&L Accounts view for missing business rules, and look for invariances (red crossed-out values). [image]

### What does the message "Would you like to break the link and proceed with loading the invoice" mean?
The operations invoice corresponding to the financial invoice has been deleted. Review audit trail for actions pertaining to both invoices. [image]

### What is the Difference Between the Different Approval Access Rights?
- **Approve an Invoice**: Approve individual invoices directly. [image]
- **Approve Invoices**: Access list of invoices pending approval. [image]
- **Invoice Actions**: Access Invoice Actions setup area. [image]
- **Invoice Approvals**: Access Financial Control setup and Invoice approvals list. [image]

### What should I do if I receive the error about broken fixture link?
The Counter Party was amended/changed after the Freight invoice was issued, breaking the link. Do not change the CP after issuing the Freight Invoice. If needed, delete the old invoice and create a new one with the correct counterparty.

### When adding bank charges to Invoice Payments, How do I resolve "Line x Voyage is Blank"?
Enable **CFGActEnableGLValidation**. This gives control over what is mandatory per ledger code in the Chart of Accounts. [image][image][image] Set voyage number to non-mandatory for bank charges.

### Where do we view the comments entered upon invoice approval, rejection, or posting?
Comments entered in the Comment field during invoice approval/rejection/posting can be retrieved in the Report Designer. Available in the Operations Invoice datasets.

### Why am I receiving a "Duplicate business rule found:" error when saving Business Rules?
A combination of Source, Bill Code, Account Code, and Category match between two or more business rules. Modify or delete the duplicates.

### Why am I unable to select a bank for an invoice?
The bank's currency value must match the transaction's base currency. Adjust the currency setting in the Data Center module.

### Why Are CVEs Under a Head Fixture Not Included in the VPJs?
CVEs are not accrued in VPJs for OVXX voyages by design. A Head Fixture monitors own tonnage costs. It is not possible to have CVE on OVXX.

### Why are Emission Expenses not populating in the Cash In/Out column in the Voyage P&L?
Emission expenses are excluded from Cash In/Out unless Cash is selected as the Settlement Type. Allowance settlements do not involve cash transactions. [image][image][image]

### Why are mirrored invoices not automatically created?
Check that the Internal check box is selected on the Address Properties panel of the respective W-type companies. [image] If counterparty has Internal selected, mirrored invoice is auto-created.

### Why are my TC Commissions inheriting the Due Date from my TCI Payment?
When **CFGAutoGenerateTcComms** is enabled, TC Commission is generated when TCI Payment is approved/posted. The due date from TCI Payment is automatically inherited. Can be changed manually.

### Why are payments for previously posted transactions missing from the database?
Autopay can delete existing payments. Review the Interface Message List to see if autopay is responsible.

### Why are the Voyage Period Journals not picking up the offhire Bunkers and Hire?
Check that **CFGPostOffhire** is enabled.

### Why Can't I Select a Counterparty in my Broker Commission Invoice?
When **CFGFreightCommBasedOnPaidAmount** is enabled, broker commission details are enabled only when the related freight invoice has been paid. [image] Deactivate this flag to allow broker commissions before freight payment. [image]

### Why does the Actual Column Take a different Exchange Rate than the Posted Column for Freight Commission?
Default: Actual value uses Exchange Rate from Freight Contract. Enable **CFGUseInvExchInActual** to use the exchange rate from the invoice instead. Invoice must be recreated for the flag to apply.

### Why does the system assign the same invoice number for the RELT voyage as the parent voyage?
Duplicate numbering occurs when the Relet Freight Invoice is posted before the parent voyage Freight Invoice. Follow correct workflow: Create parent invoice (auto-creates relet) > Approve parent (auto-approves relet) > Post parent > Post relet.

### Why do I still see an invariant in my P&L after updating the business rules for a posted invoice?
An invariant (red crossed-out value) in the posted column is caused by missing Business Rules. Updated rules do not apply retroactively. Posted invoices must be reversed and reposted.

### Why is my PDA not Updated by my FDA?
Common reason: mismatched information between the two Disbursement invoices. Review and ensure all information matches. If using a Partner/Integration, have the third party resend.

### Why is the Counterparty XJOURNAL in EU ETS Allowance Invoices?
The XJOURNAL line represents the clearance account used to settle the liability before final transfer. Ensures expense is correctly allocated to the voyage while the balance sheet reflects allowance removal from inventory. [image]

### Why is there a line item highlighted in yellow on a Time Charter Bill/Payment?
Yellow highlighting means there are remarks (comments) about the line item. [image] Right-click > Remarks to view. [image]

### XJOU: Missing Business Rule Error in Monthly Accruals
Caused by missing codes in Ad hoc journals. [image][image][image] Reverse incorrect journals, recreate with all required codes, verify no missing business rules in Voyage PnL > Accounts view, then run Monthly Accruals again.

---

## Help Center

### How can I report a bug?
Stop all other work when the issue arises. Navigate to My Profile panel (click initials) > Submit Diagnostic Report. [image] Click Copy Report ID and submit through the Veson Nautical Help Center with further details.

### How do I fix an issue where Help Center attachments are failing to upload?
Log out of your current session, log in, and attempt to submit a new case with attachments.

### Why are incoming email replies to Jira tickets not being processed?
Solution 1: Ensure the correct email address is in the CC line (e.g., supportnotifications@veson.com for Veson Support project). Solution 2: Remove extra header information in replies that may match delimiters that strip the email. [image]

### Why has Feature Board suggestion been archived?
Suggestions without at least 10 votes within three months get "Archived" status. They can still be viewed, searched, and voted for. Other statuses: Under Consideration, Planned, Not Planned, Done, Already Exists.

---

## Integration

### Can external systems interface with IMOS?
IMOS can receive interface messages via Messaging Service Listeners and API. Interface messages must adhere to respective interface specifications. Contact Veson Support or Professional Services for assistance.

### Does Veson Nautical support Robotic Process Automation (RPA) for its products?
Veson Nautical does not support RPA in any form for any of its products. Clients should refrain from attempting to create RPA user accounts in their databases.

### FAQ - Why are TCTO voyages not included in the notifications for DA-Desk?
In OVTO/TCTO, the Operating Company is not involved in voyage operations. Configuration flag **CFGOprTypesForPortschinfoDA** controls operation types for DA-Desk notifications. Default values are TCOV & OVOV. Add other operation types to the Value field. [image] Restart messaging service after changes.

### Some Interface Messages are stuck in Pending status or are not showing up
The Messaging Service can become inundated if several processes run simultaneously. Resolve by restarting the Messaging Service. Consider increasing the Timeout threshold in the General Configuration tab.

### Why are my imported invoices not exporting to external financial databases?
Imported invoices can fail to export if the original import failed. Open Failed messages in the Interface Message List to view issues (missing items in XML, posting to closed voyage, etc.).

### Why can't I see the billinv as a table in the database?
billinv is a view, not a table, and therefore is not listed in the Tables folder.

### Why does Company Import XML not update existing records even though the status shows "Successful"?
The reference code must be indicated in the <referenceCode> field tag. If left empty, the message processes successfully but the record is not updated. **CFGEnableMultiRoleOnAddressBook** and **CFGAddBookUniqueRefCode** affect reference code behavior.

### Why does my invoice import fail even though my line items and total amount match?
May be caused by too many decimal places in line items. The invoiceImport functionality fails if currency values have more than 2 decimal places. This is a Messaging Service limitation that cannot be modified.

### Why do Market Index data not appear when the Interface Message List shows successful import?
Often caused by an erroneous space in the <CMSRouteId/> line item(s). Incorrect: `<CMSRouteId>Route_Data123 +3MON</CMSRouteId>`. Correct: `<CMSRouteId>Route_Data123+3MON</CMSRouteId>`.

### Why is a SimplePayment Message failing with error "Unable to Get Exchange Rate Between <USD> and <>"?
Caused by missing or incomplete bank details in the address book record. Navigate to Data Center > Address book > Check bank setup: ensure valid currency and valid bank code. [image]

---

## Operations

### Can I Add a Second Ops Coordinator in a Voyage
**Config Flag: CFGEnableVoyageRoles** - Enable this flag, then go to Voyage Manager > Properties and the Ops Coord 2 field becomes available. [image]

### Can I change a vessel name midway through a voyage?
With appropriate Module Rights, administrators can change a Vessel's name at any time. The new name only applies to new voyages. Old name retained for existing voyages. For time-chartered vessels, the TC contract and invoices retain the old vessel name.

### Error when scheduling a TC Out - commencing port mismatch
Clicking "Sched a Voyage" returns a save error when the commencing port on the active voyage does not match the port in the estimate. [image] Resolve by aligning the two port values.

### FAQ - Missing Business Rule error not showing in P&L even with missing source/bill Code
If the invoice amount is zero, or all invoices net to zero, the missing business rule error will not appear. [image][image][image]

### How can I add waypoints to a voyage itinerary?
Insert a port row between standard ports. Enter an AT SEA port, enter Latitude and Longitude coordinates, enter Port Function (P for passing, W for waiting). Check Miles column. [image]

### How can I approve a Veslink Form on a past consecutive voyage?
Change status of subsequent forms to "Open for Resubmit", change current voyage to 'Scheduled' (warning: port activity info will be restored, manual entries lost). [image] Approve previous forms, change voyage to Commenced, approve target form, change to Completed, then resubmit all opened forms.

### How can I create a Carbon Allowance Invoice that has a Counterparty that is not part of the TC Contract?
Use the "DOC Holder" field in the Emissions tab. [image][image][image][image] Note: You can also set the DOC Holder directly on the contract's Emissions or EU ETS tab. Requires schema version 52.7.

### How can I lock estimated values in the Voyage P&L?
**Config Flag: CFGInitialSnapshotTimeSelect** - Values: Empty (default, uses linked Estimate), Schedule (snapshot at scheduling), Commence (snapshot at commencing, allows Update Initial Snapshot function). [image][image] Set up in Data Center > Configuration Flag List.

### How can I make the Worldscale Differentials reflect on the voyage?
**Config Flag: CFGInitialSnapshotTimeSelect** - When set to "schedule", a snapshot is taken when voyage is scheduled. Change to "commence", save and refresh, then recreate the voyage from the estimate. [image][image][image][image]

### How can the Voyage Status for Claim Pending and Legal Hold be identified via Data Lake?
Status values are derived from boolean fields (Forecast, Legal Hold, Claim Pending, Cancel) represented as bitflags 4, 6, 7, and 13 on voyage.flags. Use SQL: voyage.flags & 0x0010 as forecast, voyage.flags & 0x0040 as claimPending, voyage.flags & 0x0080 as legalHold, voyage.flags & 0x2000 as cancelled.

### How Does Loaded and Discharged LNG Cargo Impact Voyage Bunker Expenses?
LNG loaded/discharged as cargo does not impact Voyage Bunker Expenses for consumption or price of Voyage End Bunkers. On consecutive voyages, Discharge Port Price and CV transfer to Initial Price and Initial CV fields, affecting BOG valuation.

### How do I add drifting to my itinerary while my vessel is awaiting orders?
Enable **CFGEnableLatLonOverride**. Add AT SEA as a port, enter lat/long, set port function to W, add estimated waiting days to Port Days. [image] Bunker consumption calculated by idle in port consumption for non-working days.

### How do I add multiple load and discharge activities on the Cargo Handling form?
On the Voyage Manager Itinerary > Cargo tab, right-click a discharge/load port line > Insert Cargo Handling Line. Save. Right-click new line > Cargo Handling. Enter cargo name, quantity, and other info.

### How do I change the speed of a previously sailed leg of a voyage?
Rollback the voyage to the desired leg: Start from most recent port > delete port activities > delete activity reports (including bunkers received if present). Perform until reaching the desired leg, then change the speed.

### How do I delete a port from a Completed voyage?
Set voyage status back to "Commenced". If consecutive, set current voyage to "Scheduled". Yes, it is possible to modify the port name directly on a Completed voyage without reverting status. [image]

### How do I delete a Proforma DA or Final DA only?
**Deleting PDA without FDA**: Clear PDA Amount, change Est In USD to 0. [image] Save. **Deleting FDA without PDA**: Clear Disbursement Inv No and Disbursement Sent. [image] Save.

### How do I delete Other Revenues/Expenses from a voyage?
Invoice must not be in posted status. You must have Read, Write, and Delete access to Other Revenues/Expenses Module Right under Port/Other Costs in Operations. [image]

### How do I derive Steam Hours from Port Activities in the Report Designer?
Steam Hours is system-derived and not available in Report Designer. Create a new column with custom expression: VoyageItineraries.Miles/VoyageItineraries.SpeedToPort. [image][image]

### How do I hide reversed line items in the Final Freight Statement?
Enable configuration flag **CFGRemoveIncrementalReversedLinesInFinalFreight**.

### How do I reset the voyage status to correct commence date of a consecutive voyage?
Set voyage statuses to scheduled (clears port activities), save the last known voyage with correct completion date, ensure all voyages are selected as consecutive.

### How is the field Total Tax calculated in Port Advance/DA?
Three fields: Total of all tax estimates (Port Expense Estimate * Estimated Tax Rate), Total of all actual taxes (Actual Amount Disbursed * Actual Tax Rate), and Total of all differences. [image][image]

### How to combine load/discharge itinerary lines of multiple cargoes into a single port record?
Right-click first cargo handling line > Split Cargo Handling Line. [image][image] Copy second cargo info to new line. [image] Back to Port/Date tab > Delete Port. [image] One itinerary line with both cargoes remains. [image]

### How to Default the Laycan To Field to 2359 for New Cargoes
**Config Flag: CFGLaycanDurationInclusive** - Disable (set status to N). Then "Laycan to" defaults to 23:59 for new cargoes. [image] Applies to new cargoes only.

### How to include Financial Attachments in Voyages
Add invoice-specific attachments within individual financial invoices. For general attachments, use Voyage Attachments. [image] Consider using Voyage Notes with "Finance" category for segregation. [image][image]

### How to invoice an external charterer for whole or parts of freight using Spot Out?
Right-click on VC In > Create Spot Out. This creates a new cargo automatically linked to the original VC In as a relet. Fill out details in the linked Cargo contract, then create a freight invoice. [image]

### How to search Port Expenses excluding rebills
Right-click the port > Port Expense Search. [image] Use the Expense Type dropdown to include/exclude expense types. [image]

### How to select the correct freight when there are multiple freight rate options in Cargo/COA
Define all possible loading/discharging ports on "Itin. Options" tab. [image] Define all combinations on "Pricing" tab. [image] System automatically reflects the matching rate.

### How to set up Port Activities ROBs to drive the Carbon Calculator (MRV/Berth-to-Berth)
Structure: PS to AF (Sea), AF to LL (Port), LL to PE (Sea). [image] Define Activity Types and ROBs under Data Center > Port Activities. [image]

### IMOS - Configurations to be updated at the start of a new calendar year
Check: Account Periods (create new record), Invoice Number (verify Reference Year in Document Numbers), Voyage Number (if **CFGVoyageNoFormat** and **CFGUseGlobalVoyageNumbering** both enabled, toggle the latter).

### IMOS - Why does my freight invoice reflect CP Qty although CP terms say Bill By: BL Qty?
Set up overage term in CP Terms Details. Check Cargo Tolerance Options Type. System defaults BL Qty to CP Qty when ANY loading activities have not been lifted.

### Unable to complete a voyage due to "Activity reports have been entered after port departure at the last port"
[image] The final activity report must be "T" (Terminating) or "D" (Departure) type. Navigate to the last departure port and delete any activity report that is not type T or D.

### What does "Failed to include cargo info in fixture notification XML" mean?
Two causes: Counterparty on cargo contract doesn't match address book entry, or cargo type doesn't match a "Cargo" in data center. [image]

### What does Failed to synchronize cargo data mean?
The itinerary row is locked for a specified port. Due to vessel having sailed from the port or having port/bunker expenses linked to it. [image]

### What does it mean when a transit port (port function P or I) is light blue in the itinerary?
The port function has been manually entered (not auto-populated by IMOS). The transit port is locked. [image]

### What is the source of the Company column data in the Claims List?
For Laytime Claims: Voyage Manager > Properties > Company field. For normal Claims: Claim > Claim tab > Company field.

### Why am I not able to change the voyage status from "Completed" to "Commenced"?
Happens when **CFGAutoCompleteVoyage** is enabled and departure Date/Time for the last port has been entered. Change the flag value to N. [image]

### Why am I unable to add a commencing port?
If the voyage has already commenced and the vessel is at the loading port, it's not possible to add another port before this. [image] Delete Port Activities and Activity Reports or change voyage status to "Scheduled".

### Why am I unable to save a voyage after correcting errors and warnings?
Refresh the page, copy the Estimate, delete the current Voyage, and schedule a new Voyage from the newly created Estimate.

### Why am I unable to update the "Chtr Specialist" field?
The field is driven by the Voyage Fixture in Chartering. [image] The Voyage Fixture object rights must be given to the user. Having full Voyage Manager rights is not sufficient. [image][image]

### Why are my Emission Expenses missing from Voyage P&L when "Include in PnL" checkbox is selected?
Check the TC emissions tab. [image] Settlement Type should be anything EXCEPT N/A. If N/A, Emissions are always excluded. [image]

### Why are the Voyage P&L (Act) and Voyage P&L (Est) columns blank in the Voyages list?
Requires **CFGCacheVoyPnl** to be enabled and a "current" snapshot to exist (manually via "Snapshot" button in Voyage P&L). Save the voyage to update reporting outlets.

### Why can't I access Demurrage Root Cause Analysis?
Both "Demurrage: Demurrage Activity" and "Demurrage: Root Cause Analysis" access rights must be configured.

### Why did my actual tolls cost disappear from the P&L after entering port expenses?
When port function I (Canal transit) is selected in estimates, estimated costs fall under Tolls. When actual port expenses use a non-Tolls ledger code, the estimated Tolls cost is automatically removed.

### Why did Voyage Status change from Completed to Closed?
A user manually changed it (one-by-one or bulk closing). Check IMOS Audit Trail, add Last Modified On/By columns, check Voyage Manager Revisions panel. Cannot bulk reverse - must be done manually.

### Why does an additional "uninvoiced" line appear under Emission costs in Voyage PnL?
[image] The emission invoice doesn't cover the whole period of the voyage. Amend the Allowance Invoice duration to match the voyage duration. [image][image]

### Why does Company Code in Voyage Manager differ from the Vessel Properties?
Creating from Fixture: Company Code from Estimate flows to Fixture then Voyage. Creating from TC Contract: Company Code from TC contract is used.

### Why does my manual Demurrage/Despatch Calculation differ from the Laytime Calculation menu?
Discrepancies stem from HH:MM Format being enabled (time in hours:minutes vs. days/decimals). Calculation based on days: Demurrage Amount = Balance Days x Rate per Day. Based on hours: Demurrage Amount = Decimal Hours x Daily Rate / 24.

### Why does my voyage fail to synchronize?
Caused by information that contradicts information on a consecutive voyage. Compare port activities between voyages. Common result: overlapping commencement/completion times. Change these times and save. [image]

### Why doesn't "Opr Qty" reflect on the Bunker invoice, when we have multiple liftings?
Bunkering forms/reports for two fuels are sent/created separately so they cannot link to one Bunker Purchase. IMOS doesn't support invoicing bunkers from multiple Activity Reports on a single invoice. Both liftings need to be in one report. [image]

### Why does the data in a report or IMOS list not match what is found in the Voyage?
Lists display data from the current snapshot; Voyage Manager P&L shows live, real-time values. The 'current' snapshot updates every time the voyage is saved.

### Why does voyage bunker consumption not appear in the Voyage P&L?
Possible causes: Bunker inventory price is zero (no price entered), or Business Rules are missing (VBNK - VCXXX where XXX = fuel type code), or mapped chart of accounts are not of Expense type.

### Why do Transit Ports have their Port Sequence numbers change when adding or removing a port?
Transit ports (canals, passing points) are auto-inserted by the distance calculation. To preserve port sequence numbers, select "Lock Transit Port" from port options dropdown. [image][image][image]

### Why is a vessel's newly added fuel type not appearing in Voyage Bunkers?
New fuel types don't appear on existing voyages. Uncommence voyage > Delete > Open estimate > Open Vessel Details > Save vessel > Synchronize > Reschedule voyage.

### Why is bunker consumption in the Voyage P&L different from the linked Estimate?
Possible reasons: Estimate was created after the Voyage, or FIFO Queue is not enabled. Enable **CFGEnableVoyestInitBunkerQueue** for FIFO calculation in Estimates.

### Why is Cargo deleted when removed from a voyage itinerary?
Default behavior deletes cargoes created in Voyage Manager when removed from voyage. Enable **CFGPreserveGeneratedCargoes** to preserve them.

### Why is Demurrage or Despatch not showing on the Actual P&L Column?
Review the Laytime Status. If status has Default Value of "Cleared", the P&L check box is not ticked. If "Selected", it is ticked.

### Why is my IMOS list exporting as an empty Excel file?
Caused by filters applied to the list that don't have any values set (blank filters). Remove or update empty filters, then export again.

### Why is the despatch/demurrage invoice status showing 'Posted' even though not posted?
If demurrage is allocated to other counterparties in the Demurrage Allocation Summary, the status automatically shows as Posted. To remove: Reject the initial invoice, delete all cost allocations.

### Why is the discharge port(s) in the operations itinerary not appearing in my CP Terms Details?
Users may overlook filling in the Cargo column in the Voyage itinerary for each port. Navigate to Itinerary > Cargo tab > locate missing cargo > select cargo grade > save.

### Why is there a discrepancy between the cargo booking screen and the database?
The Cargo Booking displays last-saved values. Updating a lifting does not automatically update the booking. The database shows values from the last time the booking was viewed and saved.

### Why is voyage bunker consumption different from Vessel details?
By default, Voyage Manager prioritizes consumption from the Performance tab of the linked Head Fixture or TC In. Enable **CFGExcludeTcConsFromBunkerCalcs** to use Vessel Consumption Tab instead.

### Why only one freight rate is applied to different cargo grades in freight invoice?
For different freight rates, create separate cargo contracts so the correct rate is picked up for each cargo grade.

### Will the total port days at an M-port change after importing a cargo?
No, the original total port days at the M-port will be preserved. Extra port days (XPD) are automatically adjusted so the sum still equals the original total.

---

## Sustainability

### How is the Energy Penalty constant calculated for FuelEU?
Two variables: EUR 2,400 per tonne of VLSFO equivalent energy exceeding the limit, and 41,000 (constant representing energy equivalent of 1 MT of VLSFO). Energy Penalty = EUR 2,400 / 41,000 = approximately 0.058.

### Why is the Carbon/Emission Allowance Invoices a Journal?
Allowance Invoices are implemented as journals (not AR/AP invoices) because: 1) They create/adjust a balance-sheet liability for allowances, not an open receivable/payable. 2) Settlement is via Allowance Transfers, not cash payment/receipt tracking. The flow: Post Allowance Invoice (creates journal) > Perform Allowance Transfers (transfer journals, close/move liability using Carbon Allowance inventory).

### Why is the energy calculated for bunkers in FUEL EU not as expected?
Total Energy (MJ) = MT x 1,000,000 x LCV. LCV is defined in Fuel/Lube Types. [image] On a bunker lifting, fuel factors can be defined specifically and will override defaults. If Fuel Factors are not defined properly, this can lead to 0 MJ energy production. [image][image]

---

## Time Charter

### FAQ - Explanation of Bunkers on Consumption
On TC Out Bunkers tab, "Bunkers on Consumption" calculates delivery/redelivery adjustments. Cleared (default): Can cause massive P&L swings with price differences. Selected: Bunkers consumed calculate based on inventory prices; only delivery/redelivery quantity and pricing differences appear on P&L.

### FAQ - What is the calculation logic behind each CVE "Rate Type"?
Three Rate Types: **Per 30 Days** (Rate / 30 * days), **Average Monthly** (Rate * 12/365 or 12/366 * days), **Monthly** (Rate / Actual Days in Month). [image][image][image] Prorating behavior depends on **CFGAlwaysProrateMonthlyTCRates**: When N, exact month match bills full rate; when Y, always prorates by exact days. [image][image][image][image]

### How do I cancel a Time Charter contract?
Change Status to Canceled. Ensure all scheduled voyages linked to the TC have been deleted (including Canceled status voyages). Cancel TCO before TCI.

### How do I clear the Last TCI Voy check box?
For Trip TC contracts, you cannot clear it. Change Contract Type to not be Trip TC, then you can clear it. The check box is selected by default for Trip TC to maintain the link between the last port and TC redelivery.

### How do I relink a Time Charter contract to a voyage?
Red values in Proj/Act fields indicate manual entry (unlinked). Scenario 1 (Voyage Completed, TC Redelivered): Clear manual entries in TC > Change status from Redelivered to Delivered > Save > In Voyage: set to Commenced > Save > set to Completed > Save. Scenario 2 (Voyage Commenced, TC Delivered): Clear manual entries > Change status from Delivered to Fixed > Save > Save voyage. [image]

### How is TCO bunker adjustment calculated?
Variables: VB1 (FIFO value at delivery), TC1 (TCO delivery value), VB2 (FIFO value at redelivery), TC2 (TCO redelivery value). Scenario 1: Adjustment = TC1 - VB1 (appears at delivery). Scenario 2 (with Bunkers on Consumption): Adjustment = (TC1 - VB1) + (VB2 - TC2) (appears at redelivery).

### Logic behind calculated index-hire rates in Unpriced Component Rate Breakdown
Index-hire rates link hire to a market benchmark. System calculates adjusted market rate for each date, determines which range applies, then applies the range formula. Example: General Correlation * Individual market rate = Adjusted rate; compare against ranges; apply formula (Index - Level) * Correlation + Offset. [image]

### Why am I unable to edit Bunker Breakdown in the Time Charter Out contract?
If values exist in "Paid by Operator" row, Bunker Breakdown cannot be edited. [image] Alternative 1: Edit all bunker liftings "Paid by Operator" to change "For Account" values. Alternative 2: Change "For Account" from "Operator" to "TCO Charterer" > edit breakdown > change back. [image]

### Why does my Time Charter contract's Proj/Act GMT Delivery field appear in red font?
Red values are entered manually instead of pulled from the voyage. [image] Clear both dates > Ensure status is 'Delivered' > Save > Navigate to first voyage > Save > Return to TC. [image][image][image][image]

### Why does my Time Charter Hire amount seem incorrect?
Many variables affect the amount. Fewer days in previous month creates higher generalized rate. Example: 1062500/28*.46875 = 17787.39 vs 1062500/31*.46875 = 16066.03, difference = 1721.36. [image]

### Why is there no voyage number in Time Charter Commission Payment line item?
May already have an Incremental Hire invoice raised ahead of the hire commission. Delete the Incremental Hire invoice, raise commission invoice, then raise Incremental Hire invoice at end of TC period. [image]

### Why Period From date in TCO Bill is not based on Proj/Act GMT delivery date?
Before vessel delivery (status: Fixed), "Period From" shows Est GMT date. [image] After delivery (status: Delivered), "Period From" shows Proj/Actual Delivery date. [image]

### Will the "To GMT" field for a hire rate be extended automatically if voyage redelivery is extended?
No. Only Delivery and Redelivery Date/Time are driven by the voyage. The "To GMT" in the Pricing grid must be manually updated. [image]

---

## Trading & Risk

### Allocating Carbon Allowance Invoice to Companies Based on Settlement and Match Types
Three settlement types: Cash, Allowance, and Hybrid. Available for TC In/Out (with **CFGEnableTCEmissionsAllocation**) and Cargo/COA/VC In (with **CFGEnableVCCOAEmissionsAllocation**). Cash: counterparty is contract company. Allowance: counterparty is contract company; Match Type (N/A, COMPANY, STRATEGY, COMPANY+STRATEGY) filters allowance options. [image] Includes full workflow summary for Allowance Invoice creation to Transfer generation.

### Baltic Exchange 4TC_P to 5TC_P Transition
Baltic Exchange will cease 4TC_P publication on January 30, 2026. Replaced by 5TC_P. After January 15, 2026, open positions converted at differential of 1,336. Action: Close 4TC_P positions and open 5TC_P; update index-linked TC contracts.

### Can I automatically link FFA or bunker swap paper trading positions to a voyage P&L?
No fully automated way. Possible via FFA Detail Import XML integration: 1) Import FFA trade using FFADetailImport XML. [image] 2) Link trade to cargo contract using cargo XML with <linkedTrade>. [image] Once cargo is added to voyage, trade appears in voyage PnL. [image]

### Can I link more than one voyage or cargo to a single bunker trade?
By default, only one linked trade per period. Enable **CFGLinkPaperTradeQty** for quantity-based linking, allowing splitting a single trade across multiple voyages/cargoes. [image][image]

### How to Enter Two Linked Cargos for the same Trade Period?
Default: single Linked Cargo per trade period. [image] Enable **CFGLinkPaperTradeQty** to allow quantity-based linking within a period, splitting quantity between Linked Trades.

### How to fetch specific contracts when running Trading Exposure reports
Step 1: Create new Trading Strategy for target contracts. [image] Step 2: Create Trading Filter selecting only that Strategy. [image] Step 3: Select the Strategy in respective Trades/Contracts. [image] Use the filter in report parameters. [image][image]

### What causes the "invalid culture identifier" error in downloading the Trade Details List?
Caused by Windows Region settings set to automatic or general locations (English - World/Europe). Set region to a specific area (e.g., United Kingdom). [image]

### Why are the PnL values in the Trading lists empty?
Result of: 1) Missing Trading Snapshot, or 2) Trading Profile settings excluding some trades. [image] Values populated by Trading P&L snapshot. Check Trading Profile checkboxes (e.g., "Exclude Internal Trade").

### Why changes to volatility values in Market Data do not trigger automatic recalculation of P&L value for FFA Options?
The Turnbull Wakeman model does not consider a change of sign. Whether positive (+75.75) or negative (-75.75), the P&L value stays the same. A trigger occurs when the value magnitude changes (e.g., 75.75 to 60.0). [image][image][image]

### Why does the Rate field for a Cargo contract in the Trade Details Drilldown not match the Net Daily TCE in the linked Benchmark Estimate?
Common cause: missing fuel grade configuration in the Cargo contract's Exposure tab. Without this, IMOS cannot factor bunkers against freight revenue, resulting in inflated Rate value. [image]

### Why do I not see Unrealized P&L, Realized P&L, and Total P&L values in the list view?
Populated by Trading P&L snapshot. Create a Trading Profile and Trading Snapshot scheduled task. Values only update when snapshot runs.

### Why do I see exposure in the Trading P&L Summary for months that do not have planned liftings?
May occur if more CP liftings than actual created liftings in the COA. Extra CP liftings are prorated and calculate exposure. Reduce CP liftings to match actual.

### Why is a vessel being displayed under the Cargo Contract as well as TCI Contracts in the Trading P&L Summary?
When cargo is scheduled under a TC voyage, the voyage PnL shows under cargo and TCI due to realization rules. TCI shows a line item but no exposed values because a voyage exists for that period.

### Will COA liftings with a status of "inquiry" be taken into account for Trading P&L exposure?
Not included by default. Check "Include Inquiry Cargoes" profile flag in the Trading Profile workspace.

---

## Voyage Reporting

### An error occurred when receiving an offline forms submission: Failed to decompress Zip data
The form's data was corrupted during compression. Often due to browser version. Download and run the most recent browser version and re-send/re-download forms.

### Can I correct the Voyage Number on a Veslink Form?
Cannot be changed after approval. Reject all forms for the specific voyage and resubmit with correct information. [image]

### Can I move Veslink Forms from one voyage to another if approved for the wrong voyage?
Not transferrable between voyages. Reject the approved form and resend with correct voyage number. If NOT approved, change voyage number within the form.

### Can I submit Veslink form attachments via the API?
Yes. POST and GET endpoints available. Use the form Id/guid from initial submission. Only send attachments to forms your company has previously submitted. One POST per file.

### How can I indicate that a Veslink form is in local time when submitting forms via API?
Remove the time zone suffix from the date/time. Note: for At Sea noon reports, you must indicate a specific time zone; "Local" is not available.

### How do I fix the issue where some fields in my custom Form Designer form not appearing in the Port Activities list?
Occurs if multiple fields map to the same Port Activity with one conditionally visible. Solutions: Create a new activity to separate fields, or combine into one field.

### How do I register as an agent in Veslink?
Access https://veson.com/veslink-agent-registration/ and provide required information. Fill out all fields for faster processing.

### How to Add Attachments on the Veslink Agent Portal
Select a link under Forms column, input information, Save Draft/Submit, then click "Add Attachment" button. Multiple documents at once (max 20MB). NOTE: Attachments in Port Disbursement forms not viewable in PDA's "Attachment" button.

### How to find a veslink form in status Being processed by IMOS and Reject it?
Go to Veslink Dashboard > Identify vessel codes > Use API to find forms > Use GUID to Reject > Go to Company Administration > Veslink > filter by GUID > select 'Reject' to IMOS > click Reset Forms.

### I made a change to a vessel in the IMOS, but why is the change not flowing into the Veslink Forms?
Changes to a vessel in IMOS do not show on already downloaded Veslink Forms. Re-download the forms. If platforms haven't synced, navigate to Veslink Settings > System Configuration > Interfaces and perform a master data reset.

### Importing VFML form
VFML form import is disabled due to security concerns (client-side code injection). To request: Prepare VFML in ZIP format, submit support ticket with explicit permission for Veson team to import.

### Is it possible to set up different conditions to auto approve Veslink forms?
Not currently possible. Auto-approval works at form level, not based on specific fields. Set Validations and Warnings at form element level.

### What does the 'Voyage has No Arrived Ports' error mean on my Departure Notice?
No ports in 'Arrival' Status - either no Arrival Notices submitted or all ports already have Departure Notices. [image]

### What happens to my data when I reject a previously approved Veslink form?
Rejecting does not reverse voyage data in the IMOS database. No automatic changes occur. You must manually update the voyage to reverse any changes.

### What is the correct order for submitting Veslink forms?
Can be sent in any order, but must be approved in order: Arrival Notice, Noon Report in Port, Cargo Handling Form, Bunkering Form, Departure Notice, Statement of Facts. Once approved, changes cannot be made.

### When should the "In Transit" option be used in a noon report?
Used while the vessel is navigating a passing point or canal. "At Sea" is for open sea navigation. To disable, enable "Hide In Transit location option" in form group settings.

### Where does the 'Effective Date' on forms pull from?
If Form Designer form has a field with ID ReportTime, that is used. For Standard Forms, a hidden date field is used which gets set to PS activity time if it exists, otherwise the earliest activity time.

### Where do I enter the "Performance Warranty" details found in the Voyage Performance Report
Values taken from the Time Charter under the Performance tab. [image][image]

### Why am I receiving voyage reports from a vessel my company hasn't operated in while?
Caused by the vessel master using old Veslink Forms mapped to your organization. Deactivate the vessel in Data Center and remove from all active Veslink Form Groups.

### Why are values entered in Voyage Reporting forms rounding up?
In Form Designer, verify element Type is set to Decimal and Decimal Places is set to a value greater than 0. [image]

### Why can't the port agent see the Forms link in Veslink?
Default Form Sharing may not be enabled for the nominated agent. Enable Form Sharing by entering specific Vessel, Voyage Number, and Partner Agent, then select forms to share.

### Why is data from Approved Voyage Reporting forms not updating the voyage?
The imosmsg user handles importing/processing. If imosmsg lacks Object Rights permissions for Company, Vessel, or Vessel Type, form data will not be processed.

### Why is my custom MRV report displaying negative consumption and/or CO2 emissions?
Likely caused by incorrect bunker data. Navigate to Voyage Manager > Reports > Voyage Operational Report. Check for and correct errors such as negative propulsion values. Save Activity Reports and Voyage, then refresh report in Analytics.

### Why is my Forms List empty?
Possible that no columns are enabled. Click the "column" icon at top of page to reveal column selection panel and select columns to display. [image]

---

## Daylight Saving

### Daylight Saving FAQ
Does IMOS acknowledge daylight savings time? Yes. For example, a Laytime Port Activity with DateTime of 3/14/21 2 am CST (when daylight saving starts) is automatically changed to 3/14/21 3 am when tabbing out of the cell.

---

## Other

### IMOS - Setting ribbon color
Set the flag **CFGLibCrMasthead**. In the value box, set 3 HEX colours separated by a comma (e.g. #469130, #469130, #469130). For a gradient, select different color codes.

---

## Image References Summary

FAQ entries containing [image] references (screenshots/diagrams):

- Administration: 0 images
- Analytics: 0 images
- API: 2 images
- Bunkering: 14 images
- Chartering: 24 images
- Claims: 3 images
- Configuration Flags: 2 images
- Cross-Platform: 3 images
- Data Center: 11 images
- Distances: 4 images
- Error Messages: 9 images
- Financials: 22 images
- Help Center: 2 images
- Integration: 2 images
- Operations: 30 images
- Sustainability: 3 images
- Time Charter: 18 images
- Trading & Risk: 12 images
- Voyage Reporting: 3 images
- Daylight Saving: 0 images
- Other: 0 images
