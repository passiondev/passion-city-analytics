WITH AddressCTE AS (
    SELECT
        p.Id AS PersonId,
        l.Street1,
        l.Street2,
        l.City,
        l.State,
        l.PostalCode,
        l.Country,
        l.GeoPoint.Lat AS Latitude,
        l.GeoPoint.Long AS Longitude
    FROM Person p
    INNER JOIN GroupLocation gl
        ON gl.GroupId = p.PrimaryFamilyId
        AND gl.GroupLocationTypeValueId = 19   -- Home (change if you want Work = 20, Previous = 137)
    INNER JOIN Location l
        ON l.Id = gl.LocationId
    CROSS APPLY (
        SELECT TOP 1 gl2.Id
        FROM GroupLocation gl2
        WHERE gl2.GroupId = p.PrimaryFamilyId
          AND gl2.GroupLocationTypeValueId = gl.GroupLocationTypeValueId
        ORDER BY gl2.Id DESC   -- or CreatedDateTime if you want "most recent"
    ) pick
    WHERE gl.Id = pick.Id
),
Phone AS (
    SELECT pn.PersonId,
           pn.NumberFormatted,
           ROW_NUMBER() OVER (PARTITION BY pn.PersonId ORDER BY pn.CreatedDateTime DESC) AS rn
    FROM PhoneNumber pn
    WHERE pn.NumberTypeValueId = 12
)
SELECT DISTINCT
    fa.Name AS FundName,
    ft.Id AS TransactionId,
    pa.PersonId,
    p.PrimaryFamilyId,
    p.LastName + ' Family' AS FamilyName,
    p.FirstName,
    p.LastName,
    p.Email,
    ph.NumberFormatted AS PhoneNumber, 
    -- Replace scalar UDF calls with JOIN to Address table if possible
    -- dbo.ufnCrm_GetAddress(p.Id, 'Home', 'Street1') AS StreetAddress1,
    -- dbo.ufnCrm_GetAddress(p.Id, 'Home', 'Street2') AS StreetAddress2,
    -- dbo.ufnCrm_GetAddress(p.Id, 'Home', 'City')     AS City,
    -- dbo.ufnCrm_GetAddress(p.Id, 'Home', 'State')    AS [State],
    -- dbo.ufnCrm_GetAddress(p.Id, 'Home', 'PostalCode') AS PostalCode,
    a.Street1,
    a.Street2,
    a.City,
    a.State,
    a.PostalCode,
    p.GivingId,
    ctype.Value AS CurrencyType,
    cctype.Value AS CreditCardType,
    ftd.Amount,
    ft.TransactionDateTime,
    ft.BatchId,
    fb.Name AS BatchName,
    ftd.Summary,
    rfr.Value AS RefundReason,
    ftr.Id AS RefundTransactionId,
    ftr.RefundReasonSummary,
    ft.TransactionCode,
    fpd.AccountNumberMasked,
    ft.CreatedDateTime,
    ft.ModifiedDateTime,
    ft.CreatedByPersonAliasId,
    ft.ModifiedByPersonAliasId,
    ft.SourceTypeValueId
FROM FinancialTransaction ft
INNER JOIN FinancialTransactionDetail ftd ON ft.Id = ftd.TransactionId
INNER JOIN FinancialAccount fa ON ftd.AccountId = fa.Id
INNER JOIN FinancialPaymentDetail fpd ON ft.FinancialPaymentDetailId = fpd.Id
LEFT JOIN FinancialBatch fb ON ft.BatchId = fb.Id
LEFT JOIN FinancialTransactionRefund ftr ON ft.Id = ftr.OriginalTransactionId
LEFT JOIN DefinedValue ctype ON fpd.CurrencyTypeValueId = ctype.Id AND ctype.DefinedTypeId = 10
LEFT JOIN DefinedValue cctype ON fpd.CreditCardTypeValueId = cctype.Id AND cctype.DefinedTypeId = 11
LEFT JOIN DefinedValue rfr ON ftr.RefundReasonValueId = rfr.Id AND rfr.DefinedTypeId = 37
INNER JOIN PersonAlias pa ON ft.AuthorizedPersonAliasId = pa.Id
INNER JOIN Person p ON pa.PersonId = p.Id
LEFT JOIN Phone ph ON p.Id = ph.PersonId AND ph.rn = 1
-- Replace this with proper Address table if you can; scalar functions should be avoided
LEFT JOIN AddressCTE a ON a.PersonId = p.Id
WHERE ft.TransactionDateTime >= '2025-07-01'
  AND ft.TransactionDateTime < '2026-03-01'
  AND (ft.SourceTypeValueId IS NULL OR ft.SourceTypeValueId <> 2521)
  AND fa.Id IN (72,49,43,74,51,60,5,17,73,50,31,41,77,79,67,90)
ORDER BY fa.Name;
